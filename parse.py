from pycamt import parser as camtparser
import csv

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
        # "Amount": (
        #     tx_detail.find(".//Amt", self.namespaces).text
        #     if tx_detail.find(".//Amt", self.namespaces) is not None
        #     else None
        # ),
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

