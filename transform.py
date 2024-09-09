from firefly import Firefly
import firefly_iii_client as ff
import datetime
import re
import uuid

class BaseTransformer:
    def __init__(self, firefly, debug=False):
        self.firefly = firefly
        self.debug = debug 
        self.transforms = []
        self.tag = "import-{}-{}".format(datetime.date.today().isoformat(), str(uuid.uuid4().fields[-1])[:5])
    
    def transform(self, tx):
        for t in self.transforms:
            tx = map(t, tx)
        
        return tx
    
    def setOwnAccount(self, iban):
        self.account = self.firefly.getAssetAccountByIban(iban)
    
    def tagTransform(self, tx):
        if tx.tags:
            tx.tags.append(self.tag)
        else:
            tx.tags = [self.tag]
        return tx

class AppkbTransformer(BaseTransformer):

    DEBIT_REGEX = re.compile(r"Debitkarten-\S+ (\d+.\d+.\d+ \d+:\d+) (.+) Kartennummer: ([\d\*]+)")
    TWINT_REGEX = re.compile(r"TWINT-\S+ (.+) (\d{12,20})")
    def __init__(self, firefly, debug=False):
        super().__init__(firefly, debug)
        self.transforms = [
            self.baseTransform,
            self.ibanTransform,
            self.debitCardTransform,
            self.twintTransform,
            self.unpackTransform,
            self.tagTransform,
        ]
    
    def baseTransform(self, camt):
        if self.debug:
            import pprint
            pprint.pprint(camt)

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
    
    def unpackTransform(self, tx):
        return tx['firefly']
