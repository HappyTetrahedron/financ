from pycamt import parser as camtparser
import requests
from firefly import Firefly
import firefly_iii_client as ff
import datetime
import re
import uuid

# behold, monkey patching:
def my_extract_transaction_details(self, tx_detail):
    """
    Extracts details specific to a transaction.

    Parameters
    ----------
    tx_detail : Element
        The XML element representing transaction details.

    Returns
    -------
    dict
        Detailed information extracted from the transaction detail element.
    """

    return {
        "EndToEndId": (
            tx_detail.find(".//Refs//EndToEndId", self.namespaces).text
            if tx_detail.find(".//Refs//EndToEndId", self.namespaces) is not None
            else None
        ),
        "AccountServicerReference": (
            tx_detail.find(".//Refs//AcctSvcrRef", self.namespaces).text
            if tx_detail.find(".//Refs//AcctSvcrRef", self.namespaces) is not None
            else None
        ),
        "MandateId": (
            tx_detail.find(".//Refs//MndtId", self.namespaces).text
            if tx_detail.find(".//Refs//MndtId", self.namespaces) is not None
            else None
        ),
        "Amount": (
            tx_detail.find(".//Amt", self.namespaces).text
            if tx_detail.find(".//Amt", self.namespaces) is not None
            else None
        ),
        "CreditorName": (
            tx_detail.find(".//RltdPties//Cdtr//Nm", self.namespaces).text
            if tx_detail.find(".//RltdPties//Cdtr//Nm", self.namespaces) is not None
            else None
        ),
        "CreditorIBAN": (
            tx_detail.find(".//RltdPties//CdtrAcct//Id//IBAN", self.namespaces).text
            if tx_detail.find(".//RltdPties//CdtrAcct//Id//IBAN", self.namespaces) is not None
            else None
        ),
        "DebtorName": (
            tx_detail.find(".//RltdPties//Dbtr//Nm", self.namespaces).text
            if tx_detail.find(".//RltdPties//Dbtr//Nm", self.namespaces) is not None
            else None
        ),
        "DebtorIBAN": (
            tx_detail.find(".//RltdPties//DbtrAcct//Id//IBAN", self.namespaces).text
            if tx_detail.find(".//RltdPties//DbtrAcct//Id//IBAN", self.namespaces) is not None
            else None
        ),
        "RemittanceInformation": (
            tx_detail.find(".//RmtInf//Ustrd", self.namespaces).text
            if tx_detail.find(".//RmtInf//Ustrd", self.namespaces) is not None
            else None
        ),
    }

camtparser.Camt053Parser._extract_transaction_details = my_extract_transaction_details

class Parser:

    DEBIT_REGEX = re.compile(r"Debitkarten-\S+ (\d+.\d+.\d+ \d+:\d+) (.+) Kartennummer: ([\d\*]+)")
    TWINT_REGEX = re.compile(r"TWINT-\S+ (.+) (\d{12,20})")
    def __init__(self, inFile, firefly, debug=False):
        with open(inFile) as camtfile:
            self.parser = camtparser.Camt053Parser(camtfile.read())
        self.debug = debug
        self.iban = self.parser.get_statement_info()['IBAN']
        self.firefly = firefly
        self.account = firefly.getAssetAccountByIban(self.iban)
        self.tag = "import-{}-{}".format(datetime.date.today().isoformat(), str(uuid.uuid4().fields[-1])[:5])
    
    def parse(self):
        tx = self.parser.get_transactions()

        transforms = [
            self.baseTransform,
            self.ibanTransform,
            self.debitCardTransform,
            self.twintTransform,
        ]

        for t in transforms:
            tx = map(t, tx)

        for x in tx:
            if self.debug:
                import pprint
                pprint.pprint(x)
            if x['drop']:
                print("Dropping transaction '{}'".format(x['firefly'].description))
            else:
                print("Storing transaction '{}'".format(x['firefly'].description))
                if not self.debug:
                    self.firefly.sendTx(x['firefly'])
    
    def baseTransform(self, camt):
        newData = {
            'camt': camt,
            'drop': False,
        }

        tx = ff.TransactionSplitStore(
            amount=camt['Amount'],
            description=camt['AdditionalEntryInformation'],
            date=datetime.date.fromisoformat(camt['BookingDate']),
            type=ff.TransactionTypeProperty.DEPOSIT if camt['CreditDebitIndicator'] == 'CRDT' else ff.TransactionTypeProperty.WITHDRAWAL,
            external_id=camt['AccountServicerReference'],
            destination_id=None,
            source_id=None,
            tags=[self.tag],
        )
        if camt['CreditDebitIndicator'] == 'CRDT':
            tx.destination_id = self.account.id
            tx.source_name = camt['DebtorName']
        else:
            tx.source_id = self.account.id
            tx.destination_name = camt['CreditorName']
        if camt['RemittanceInformation']:
            tx.notes = camt['RemittanceInformation']
            tx.description = "{} ({})".format(camt['AdditionalEntryInformation'], camt['RemittanceInformation'])
        newData['firefly'] = tx
        return newData
    
    def ibanTransform(self, tx):
        camt = tx['camt']
        fftx = tx['firefly']
        if camt['CreditDebitIndicator'] == 'CRDT' and camt['DebtorIBAN']:
            source = self.firefly.getRevenueAccountByIban(camt['DebtorIBAN'])
            if not source:
                source = self.firefly.getAssetAccountByIban(camt['DebtorIBAN'])
                if source:
                    fftx.type = ff.TransactionTypeProperty.TRANSFER
                else:
                    if self.debug:
                        source = ff.AccountRead(id=-1)
                    else:
                        source = self.firefly.createRevenueAccount(camt['DebtorIBAN'], camt['DebtorName'])
            
            fftx.source_id = source.id
        elif camt['CreditorIBAN']:
            dest = self.firefly.getExpenseAccountByIban(camt['CreditorIBAN'])
            if not dest:
                dest = self.firefly.getAssetAccountByIban(camt['CreditorIBAN'])
                if dest:
                    fftx.type = ff.TransactionTypeProperty.TRANSFER
                else:
                    if self.debug:
                        source = ff.AccountRead(id=-1)
                    else:
                        dest = self.firefly.createExpenseAccount(camt['CreditorIBAN'], camt['CreditorName'])
            
            fftx.destination_id = dest.id
        tx['firefly'] = fftx
        return tx
    
    def debitCardTransform(self, tx):
        if "Debitkarten-" not in tx['camt']['AdditionalEntryInformation']:
            return tx
        match = self.DEBIT_REGEX.match(tx['camt']['AdditionalEntryInformation'])
        if not match:
            return tx
        g = match.groups()

        datetime = g[0]
        recipient = g[1]
        card = g[2]

        fftx = tx['firefly']
        if fftx.type == ff.TransactionTypeProperty.WITHDRAWAL:
            fftx.destination_name = recipient
        else:
            fftx.source_name = recipient

        addNotes = "Purchase Date: {}\nCard No.: {}".format(datetime, card)
        if fftx.notes:
            fftx.notes = "\n".join([fftx.notes, addNotes])
        else:
            fftx.notes = addNotes

        tx['firefly'] = fftx
        return tx
    
    def twintTransform(self, tx):
        if "TWINT" not in tx['camt']['AdditionalEntryInformation']:
            return tx

        match = self.TWINT_REGEX.match(tx['camt']['AdditionalEntryInformation'])
        if not match:
            return tx
        g = match.groups()

        recipient = g[0]
        number = g[1]

        fftx = tx['firefly']
        if fftx.type == ff.TransactionTypeProperty.WITHDRAWAL:
            fftx.destination_name = recipient
        else:
            fftx.source_name = recipient

        addNotes = "Twint Account ID: {}".format(number)
        if fftx.notes:
            fftx.notes = "\n".join([fftx.notes, addNotes])
        else:
            fftx.notes = addNotes

        tx['firefly'] = fftx
        return tx





if __name__ == '__main__':
    from optparse import OptionParser
    op = OptionParser()
    op.add_option('-f', '--file', dest='file', type='string',
                      help="Path of camt file")
    op.add_option('-H', '--host', dest='host', type='string',
                      help="Firefly host")
    op.add_option('-t', '--token', dest='token', type='string',
                      help="Firefly token")
    op.add_option('-d', '--debug', dest='debug', action='store_true',
                      help="Debug mode")
    (opts, args) = op.parse_args()

    firefly = Firefly(opts.host, opts.token)
    parser = Parser(opts.file, firefly, opts.debug)
    parser.parse()