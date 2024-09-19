from firefly_iii_client import TransactionTypeProperty

from firefly import Firefly
import firefly_iii_client as ff
import datetime
import re
import uuid

from utils import normalizeIban


class BaseTransformer:
    def __init__(self, firefly, debug=False):
        self.firefly = firefly
        self.debug = debug 
        self.transforms = []
        self.tag = "import-{}-{}".format(datetime.date.today().isoformat(), str(uuid.uuid4().fields[-1])[:5])
    
    def transform(self, transactions):
        transformed_transactions = []
        for tx in transactions:
            for t in self.transforms:
                tx = t(tx)
                if not tx:
                    break
            if tx:
                transformed_transactions.append(tx)
        
        return transformed_transactions
    
    def setOwnAccount(self, identifier, iban=True):
        if iban:
            self.account = self.firefly.getAssetAccountByIban(identifier)
        else:
            self.account = self.firefly.getAssetAccountByName(identifier)
    
    def unpackTransform(self, tx):
        return tx['firefly']
    
    def tagTransform(self, tx):
        if tx.tags:
            tx.tags.append(self.tag)
        else:
            tx.tags = [self.tag]
        return tx
    
    def _setOtherParty(self, fftx, party):
        if fftx.type == ff.TransactionTypeProperty.WITHDRAWAL:
            fftx.destination_name = party
        else:
            fftx.source_name = party
    
    def _addNotes(self, fftx, note):
        if fftx.notes:
            fftx.notes = "\n".join([fftx.notes, note])
        else:
            fftx.notes = note

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
                        dest = ff.AccountRead(id=-1)
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

        self._setOtherParty(tx['firefly'], recipient)
        self._addNotes(tx['firefly'], "Purchase Date: {}\nCard No.: {}".format(datetime, card))

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

        self._setOtherParty(tx['firefly'], recipient)
        self._addNotes(tx['firefly'], "Twint Account ID: {}".format(number))

        return tx

class ZkbTransformer(BaseTransformer):

    DEBIT_REGEX_DE = re.compile(r"\S+ ZKB Visa Debit Card Nr. (\S{2,6} \d{2,6}), (.+)")
    DEBIT_REGEX_EN = re.compile(r"\S+ ZKB Visa Debit card no. (\S{2,6} \d{2,6}), (.+)")
    TWINT_REGEX = re.compile(r"\S+ TWINT: (.+)")
    LSV_REGEX_DE = re.compile(r"\S+ aus Lastschrift.*: (.+)")
    LSV_REGEX_EN = re.compile(r"\S+ from LSV.*: (.+)")
    ENGLISH = {
        "Date": "Datum",
        "Booking text": "Buchungstext",
        "Debit CHF": "Belastung CHF",
        "Credit CHF": "Gutschrift CHF",
        "Value date": "Valuta",
        "Balance CHF": "Saldo CHF",
        "ZKB reference": "ZKB-Referenz",
        "Payment purpose": "Zahlungszweck",
    }
    def __init__(self, firefly, debug=False):
        super().__init__(firefly, debug)
        self.transforms = [
            self.keyTranslateTransform,
            self.baseTransform,
            self.feeTransform,
            self.purposeTransform,
            self.cardTransform,
            self.twintTransform,
            self.lsvTransform,
            self.unpackTransform,
            self.tagTransform,
        ]
    
    def keyTranslateTransform(self, csv):
        new = {}
        for k, v in csv.items():
            if k in self.ENGLISH:
                new[self.ENGLISH[k]] = v
            else:
                new[k] = v
        return new

    def baseTransform(self, csv):
        if self.debug:
            import pprint
            pprint.pprint(csv)

        newData = {
            'csv': csv,
            'dir': 'credit' if csv['Gutschrift CHF'] else 'debit',
        }

        tx = ff.TransactionSplitStore(
            amount=csv['Gutschrift CHF'] if newData['dir'] == 'credit' else csv['Belastung CHF'],
            description=csv['Buchungstext'],
            date=datetime.datetime.strptime(csv['Datum'], "%d.%m.%Y"),
            type=ff.TransactionTypeProperty.DEPOSIT if newData['dir'] == 'credit' else ff.TransactionTypeProperty.WITHDRAWAL,
            external_id=csv['ZKB-Referenz'],
            destination_id=None,
            source_id=None,
        )
        if newData['dir'] == 'credit':
            tx.destination_id = self.account.id
            tx.source_name = csv['Details']
        else:
            tx.source_id = self.account.id
            tx.destination_name = csv['Details']
        newData['firefly'] = tx
        return newData
    
    def feeTransform(self, tx):
        if "Gebühr ZKB" not in tx['csv']['Buchungstext']:
            return tx
        self._setOtherParty(tx['firefly'], "ZKB Zürcher Kantonalbank")
        return tx
    
    def purposeTransform(self, tx):
        if not tx['csv']['Zahlungszweck']:
            return tx
        self._addNotes(tx['firefly'], "Purpose: {}".format(tx['csv']['Zahlungszweck']))
        return tx

    def cardTransform(self, tx):
        if "Visa Debit" not in tx['csv']['Buchungstext']:
            return tx

        if "Card Nr." in tx['csv']['Buchungstext']:
            match = self.DEBIT_REGEX_DE.match(tx['csv']['Buchungstext'])
        else:
            match = self.DEBIT_REGEX_EN.match(tx['csv']['Buchungstext'])
        if not match:
            return tx
        g = match.groups()

        card = g[0]
        recipient = g[1]

        self._setOtherParty(tx['firefly'], recipient)
        self._addNotes(tx['firefly'], "Card No.: {}".format(card))

        return tx
    
    def twintTransform(self, tx):
        if "TWINT" not in tx['csv']['Buchungstext']:
            return tx

        match = self.TWINT_REGEX.match(tx['csv']['Buchungstext'])
        if not match:
            return tx
        g = match.groups()

        recipient = g[0]

        self._setOtherParty(tx['firefly'], recipient)

        return tx

    def lsvTransform(self, tx):
        if not ("Lastschrift" in tx['csv']['Buchungstext'] or "LSV" in tx['csv']['Buchungstext']):
            return tx

        if "Lastschrift" in tx['csv']['Buchungstext']:
            match = self.LSV_REGEX_DE.match(tx['csv']['Buchungstext'])
        else:
            match = self.LSV_REGEX_EN.match(tx['csv']['Buchungstext'])
        if not match:
            return tx
        g = match.groups()

        recipient = g[0]

        self._setOtherParty(tx['firefly'], recipient)

        return tx

class VisecaTransformer(BaseTransformer):

    def __init__(self, firefly, debug=False):
        super().__init__(firefly, debug)
        self.transforms = [
            self.baseTransform,
            self.feeTransform,
            self.depositTransform,
            self.categoryTransform,
            self.unpackTransform,
            self.tagTransform,
        ]
    
    def baseTransform(self, csv):
        if self.debug:
            import pprint
            pprint.pprint(csv)

        newData = {
            'csv': csv,
            'dir': 'debit' if float(csv['Amount']) >= 0 else 'credit',
        }

        tx = ff.TransactionSplitStore(
            amount=csv['Amount'] if newData['dir'] == 'debit' else csv['Amount'][1:],
            description="Credit Card Payment - {}".format(csv['Merchant']),
            date=datetime.datetime.fromisoformat(csv['Date']),
            type=ff.TransactionTypeProperty.DEPOSIT if newData['dir'] == 'credit' else ff.TransactionTypeProperty.WITHDRAWAL,
            external_id=csv['TransactionID'],
            destination_id=None,
            source_id=None,
        )
        if newData['dir'] == 'credit':
            tx.destination_id = self.account.id
            tx.source_name = csv['Merchant']
        else:
            tx.source_id = self.account.id
            tx.destination_name = csv['Merchant']
        newData['firefly'] = tx
        return newData
    
    def feeTransform(self, tx):
        if tx['csv']['PFMCategoryID'] != "cv_creditcardfees":
            return tx
        tx['firefly'].description = "Credit Card Fees"
        self._setOtherParty(tx['firefly'], "Viseca Credit Card Fees")
        return tx
    
    def depositTransform(self, tx):
        if tx['dir'] == 'debit':
            return tx
        tx['firefly'].description = "Credit Card Pre-Payment"
        self._setOtherParty(tx['firefly'], "Viseca Credit Card Deposits")
        return tx
    
    def categoryTransform(self, tx):
        if tx['csv']['PFMCategoryID'] == "cv_not_categorized":
            return tx
        self._addNotes(tx['firefly'], "Category: {}".format(tx['csv']['PFMCategoryName']))
        return tx


class UbsTransformer(BaseTransformer):
    TWINT_REGEX = re.compile(r"Zahlungsgrund: ([^;]+)(?:; )?TWINT-Acc")
    ACCOUNT_REGEX = re.compile(r"Konto-Nr\. IBAN: ([^;]+)")

    _prevDate = None

    def __init__(self, firefly, debug=False):
        super().__init__(firefly, debug)
        self.transforms = [
            self.baseTransform,
            self.twintTransform,
            self.ibanTransform,
            self.unpackTransform,
            self.tagTransform,
        ]

    def baseTransform(self, csv):
        if self.debug:
            import pprint
            pprint.pprint(csv)

        if csv['Beschreibung1'] == 'Diverse Daueraufträge':
            self._prevDate = csv['Abschlussdatum']
            return None
        if not csv['Abschlussdatum']:
            csv['Abschlussdatum'] = self._prevDate

        amount = csv['Belastung'] or csv['Gutschrift'] or csv['Einzelbetrag']

        newData = {
            'csv': csv,
            'dir': 'debit' if amount.startswith('-') else 'credit',
        }

        fireflyTx = ff.TransactionSplitStore(
            amount=amount,
            description=csv['Beschreibung1'],
            date=datetime.date.fromisoformat(csv['Abschlussdatum']),
            type=ff.TransactionTypeProperty.DEPOSIT if newData['dir'] == 'credit' else ff.TransactionTypeProperty.WITHDRAWAL,
            external_id=csv['Transaktions-Nr.'],
            destination_id=None,
            source_id=None,
        )
        if newData['dir'] == 'credit':
            fireflyTx.destination_id = self.account.id
            fireflyTx.source_name = csv['Beschreibung1']
        else:
            fireflyTx.source_id = self.account.id
            fireflyTx.destination_name = csv['Beschreibung1']
        newData['firefly'] = fireflyTx
        return newData

    def twintTransform(self, tx):
        match = self.TWINT_REGEX.match(tx['csv']['Beschreibung3'])
        if not match:
            return tx
        g = match.groups()

        recipient = g[0]
        if recipient.startswith("+"):
            self._addNotes(tx['firefly'], "TWINT Phone Number: {}".format(recipient))
            if tx['csv']['Beschreibung2'] == 'Gutschrift UBS TWINT':
                recipient = tx['csv']['Beschreibung1'].upper()
            else:
                recipient = tx['csv']['Beschreibung1'].replace('; Belastung UBS TWINT', '')
        else:
            recipient = tx['csv']['Beschreibung1'].replace('; Zahlung UBS TWINT', '').upper()

        tx['firefly'].description = f"TWINT: {recipient}"
        self._setOtherParty(tx['firefly'], recipient)
        return tx

    def ibanTransform(self, tx):
        match = self.ACCOUNT_REGEX.match(tx['csv']['Beschreibung3'])
        if not match:
            return tx
        g = match.groups()
        iban = normalizeIban(g[0])

        fftx = tx['firefly']

        if fftx.type == TransactionTypeProperty.DEPOSIT:
            source = self.firefly.getRevenueAccountByIban(iban)
            if source:
                source_id = source.id
            else:
                source = self.firefly.getAssetAccountByIban(iban)
                if source:
                    fftx.type = ff.TransactionTypeProperty.TRANSFER
                    source_id = source.id
                else:
                    if self.debug:
                        source_id = "-1"
                    else:
                        source = self.firefly.createRevenueAccount(iban, tx['csv']['Beschreibung1'])
                        source_id = source.id
            fftx.source_id = source_id
        else:
            dest = self.firefly.getExpenseAccountByIban(iban)
            if dest:
                dest_id = dest.id
            else:
                dest = self.firefly.getAssetAccountByIban(iban)
                if dest:
                    fftx.type = ff.TransactionTypeProperty.TRANSFER
                    dest_id = dest.id
                else:
                    if self.debug:
                        dest_id = "-1"
                    else:
                        dest = self.firefly.createExpenseAccount(iban, tx['csv']['Beschreibung1'])
                        dest_id = dest.id

            fftx.destination_id = dest_id
        return tx
