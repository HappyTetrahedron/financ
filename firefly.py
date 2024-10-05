import firefly_iii_client as ff

class Firefly:
    def __init__(self, host, token):
        self.conf = ff.configuration.Configuration(
            host = host,
        )
        self.conf.access_token = token
        self.client = ff.ApiClient(self.conf)
    
    def createTag(self, tag, date):
        fftag = ff.TagModelStore(
            tag=tag,
            date=date,
        )

        ff.TagsApi(self.client).store_tag(fftag)
    
    def sendTx(self, txSplit, debug=False):
        if txSplit.external_id:
            existing = self.getTransactionByExternalId(txSplit.external_id)
            if existing:
                print("Transaction {} already exists - skipping.".format(txSplit.description))
                return
        tx = ff.TransactionStore(
            apply_rules=True,
            fire_webhooks=True,
            error_if_duplicate_hash=True,
            transactions=[txSplit],
        )
        if debug:
            print("Debug active - not storing transaction:")
            import pprint
            pprint.pprint(txSplit)
            return
        try:
            print("Storing transaction {}.".format(txSplit.description))
            ff.TransactionsApi(self.client).store_transaction(tx)
        except ff.exceptions.ApiException as e:
            if "Duplicate of transaction" in e.body:
                print("Transaction is a duplicate: {}".format(e.body[-10:]))
            elif "Possibly, a rule deleted this transaction after its creation." in e.body:
                print("Transaction was dropped by a rule.")
            else:
                raise e
    
    def createRevenueAccount(self, iban, name):
        return self.createAccount(iban, name, ff.ShortAccountTypeProperty.REVENUE)
    
    def createExpenseAccount(self, iban, name):
        return self.createAccount(iban, name, ff.ShortAccountTypeProperty.EXPENSE)
    
    def createAccount(self, iban, name, atype, add_iban=False):
        rname = name
        if add_iban:
            rname = "{} ({})".format(name, iban)
        print("Creating {} account {} with IBAN {}".format(atype, rname, iban))
        acct = ff.AccountStore(
            iban=iban,
            name=rname,
            type=atype,
        )
        try:
            return ff.AccountsApi(self.client).store_account(acct).data
        except ff.exceptions.ApiException as e:
            if "This account name is already in use." in e.body:
                if not add_iban:
                    print("Account name is in use, retrying...")
                    return self.createAccount(iban, name, atype, True)
            raise e

    
    def getTransactionByExternalId(self, external_id):
        resp = ff.SearchApi(self.client).search_transactions(
            query="external_id:{}".format(external_id),
        )
        if len(resp.data) > 0:
            return resp.data[0]
        return None

    def getRevenueAccountByIban(self, iban):
        return self.getAccountByIban(iban, ff.AccountTypeFilter.REVENUE)

    def getExpenseAccountByIban(self, iban):
        return self.getAccountByIban(iban, ff.AccountTypeFilter.EXPENSE)

    def getAssetAccountByIban(self, iban):
        return self.getAccountByIban(iban, ff.AccountTypeFilter.ASSET)

    def getAssetAccountByName(self, name):
        return self.getAccountByName(name, ff.AccountTypeFilter.ASSET)

    def getAccountByIban(self, iban, accType):
        return self.getAccount(iban, accType, ff.AccountSearchFieldFilter.IBAN)
    
    def getAccount(self, identifier, accType, searchField):
        resp = ff.SearchApi(self.client).search_accounts(
            query=identifier,
            field=searchField,
            type=accType,
        )
        if len(resp.data) > 0:
            return resp.data[0]
        return None

    def getAccountByName(self, name, accType):
        return self.getAccount(name, accType, ff.AccountSearchFieldFilter.NAME)
