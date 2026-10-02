"""Local rotating diagnostic log. No uploaded measurement content is logged."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


def setup(root):
    path=Path(root)/'logs'/'gas_atlas.log';path.parent.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger('gas_atlas')
    if not any(getattr(h,'baseFilename',None)==str(path.resolve()) for h in logger.handlers):
        h=RotatingFileHandler(str(path),maxBytes=2*1024**2,backupCount=3,encoding='utf8')
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logger.addHandler(h);logger.setLevel(logging.INFO)
        logging.getLogger('streamlit.error_util').addHandler(h)
        from .config import VERSION
        logger.info('Запуск Газового атласа '+VERSION)
    return path


def show_error(message):
    import streamlit as st
    logging.getLogger('gas_atlas').error(str(message),exc_info=sys.exc_info()[0] is not None)
    st.error(message)
