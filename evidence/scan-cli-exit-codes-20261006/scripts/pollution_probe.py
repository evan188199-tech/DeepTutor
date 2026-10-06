import logging, sys
import deeptutor_cli.main  # module import calls configure_logging()
logging.getLogger("deeptutor.test").warning("POLLUTION-PROBE log line on stdout")
print("{}", "JSON-DATA-MARKER")
