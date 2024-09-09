from firefly import Firefly
import parse
import transform
import sys
import datetime

class FFImporter:
    def __init__(self, parser, transformer, firefly, debug=False):
        self.debug = debug
        self.parser = parser
        self.transformer = transformer
        self.firefly = firefly
    
    def process(self, filename):
        parsed = parser.parse(filename)
        if 'iban' in parsed:
            transformer.setOwnAccount(parsed['iban'])

        tx = transformer.transform(parsed['tx'])

        if not self.debug:
            firefly.createTag(transformer.tag, datetime.datetime.now())

        for x in tx:
            if self.debug:
                import pprint
                pprint.pprint(x)
            print("Storing transaction '{}'".format(x.description))
            if not self.debug:
                self.firefly.sendTx(x)


if __name__ == '__main__':
    from optparse import OptionParser
    op = OptionParser()
    op.add_option('-f', '--file', dest='file', type='string',
                      help="Path of camt file")
    op.add_option('-H', '--host', dest='host', type='string',
                      help="Firefly host")
    op.add_option('-t', '--token', dest='token', type='string',
                      help="Firefly token")
    op.add_option('-b', '--bank', dest='bank', type='string',
                      help="Bank. Supported: appkb, zkb", default="appkb")
    op.add_option('-i', '--iban', dest='iban', type='string',
                      help="IBAN of account associated with bank statement")
    op.add_option('-d', '--debug', dest='debug', action='store_true',
                      help="Debug mode")
    (opts, args) = op.parse_args()

    firefly = Firefly(opts.host, opts.token)

    parser = None
    if opts.file.endswith('.xml'):
        parser = parse.CamtParser()

    transformer = None
    if opts.bank == "appkb":
        transformer = transform.AppkbTransformer(firefly, opts.debug)
    if opts.bank == "zkb":
        parser = parse.ZkbCsvParser()
        transformer = transform.ZkbTransformer(firefly, opts.debug)
        if not opts.iban:
            sys.exit("Please provide IBAN")
        transformer.setOwnAccount(opts.iban)
    
    if not (transformer and parser):
        sys.exit("Invalid input")
        # todo better errors
    
    ffi = FFImporter(parser, transformer, firefly, opts.debug)
    ffi.process(opts.file)
