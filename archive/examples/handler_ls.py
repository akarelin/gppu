# .. archived 2026-11-22: what gppu's reduction removed from examples/handler_ls.py, as it was last


# .. from fec31bb
def main() -> None:
  app = App(config=__file__)   # .. its own configuration is its MANIFEST
  print(listing(GppuCatalog(app.my('catalog')), *sys.argv[1:2]))
