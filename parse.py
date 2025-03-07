from pycamt import parser as camtparser
import csv

from utils import normalizeIban


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
        # The top level amount field contains the total amount including bank fees, the TxDetail amount does not;
        # by not overriding the amount here we can keep the total amount which is more useful.
        # UPDATE actually, there are batch transactions, where the overall amount is the sum of the amounts of multiple transactions,
        # so using that unconditionally is also not a good idea. We probably need special handling for foreign currencies here.
        # TODO do that eventually
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


def my_extract_transaction(self, entry):
    """
    Extracts data from a single transaction entry.

    Parameters
    ----------
    entry : Element
        The XML element representing a transaction entry.

    Returns
    -------
    dict
        A dictionary containing extracted data for the transaction.
    """

    common_data = self._extract_common_entry_data(entry)
    entry_details = entry.findall(".//NtryDtls", self.namespaces)

    transactions = []

    # Handle 1-0 relationship
    if not entry_details:
        transactions.append(common_data)
    else:
        for ntry_detail in entry_details:
            tx_details = ntry_detail.findall(".//TxDtls", self.namespaces)

            # Handle 1-0 relationship - very bold to assume this data format would be sane
            if len(tx_details) == 0:
                transactions.append(common_data)
            # Handle 1-1 relationship
            if len(tx_details) == 1:
                transactions.append(
                    {
                        **common_data,
                        **self._extract_transaction_details(tx_details[0]),
                    }
                )

            # Handle 1-n relationship
            else:
                for tx_detail in tx_details:
                    transactions.append(
                        {
                            **common_data,
                            **self._extract_transaction_details(tx_detail),
                        }
                    )
    return transactions

camtparser.Camt053Parser._extract_transaction_details = my_extract_transaction_details
camtparser.Camt053Parser._extract_transaction = my_extract_transaction

class BaseParser:
    @staticmethod
    def parse(inFile):
        return {}

class CamtParser(BaseParser):
    @staticmethod
    def parse(inFile):
        with open(inFile) as camtfile:
            parser = camtparser.Camt053Parser(camtfile.read())
            iban = parser.get_statement_info()['IBAN']
            tx = parser.get_transactions()
            return {
                'iban': iban,
                'tx': tx,
            }

class ZkbCsvParser(BaseParser):
    @staticmethod
    def parse(inFile):
        with open(inFile, newline='') as csvfile:
            lines = [ l.strip('\n\r\ufeff') for l in  csvfile.readlines() ]
            reader = csv.DictReader(lines, delimiter=';', quotechar='"')
            tx = [i for i in reader]
            return {
                'tx': tx,
            }

class VisecaCsvParser(BaseParser):
    @staticmethod
    def parse(inFile):
        with open(inFile, newline='') as csvfile:
            lines = [ l.strip('\n\r\ufeff') for l in  csvfile.readlines() ]
            reader = csv.DictReader(lines, delimiter=',', quotechar='"')
            tx = [i for i in reader]
            return {
                'tx': tx,
            }

class UbsCsvParser(BaseParser):
    @staticmethod
    def parse(inFile):
        iban = None
        with open(inFile, newline='') as csvfile:
            lines = [l.strip('\n\r\ufeff') for l in csvfile.readlines()]
            while True:
                line = lines.pop(0)
                if not line:
                    break
                cells = line.split(";")
                if 'IBAN' in cells[0]:
                    iban = normalizeIban(cells[1])

            reader = csv.DictReader(lines, delimiter=';', quotechar='"')
            return {
                'tx': [i for i in reader],
                'iban': iban,
            }

class UbsCardCsvParser(BaseParser):
    @staticmethod
    def parse(inFile):
        with open(inFile, newline='', encoding='iso-8859-1') as csvfile:
            lines = [l.strip('\n\r\ufeff') for l in csvfile.readlines() if l and not l.startswith('sep=;') and not l.startswith(';;')]
            reader = csv.DictReader(lines, delimiter=';', quotechar='"')
            return {
                'tx': [i for i in reader],
            }
