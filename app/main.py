#!/usr/bin/env python3
"""
RSS to WordPress Automation System - Ponto de Entrada
"""

import argparse
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import SCHEDULE_CONFIG
from app.logging_config import setup_logging
from app.pipeline import run_pipeline_cycle
from app.cleanup import run_cleanup
from app.store import Database

logger = logging.getLogger(__name__)

def main():
    """Função principal para configurar e iniciar o aplicativo."""
    setup_logging()

    parser = argparse.ArgumentParser(description='RSS to WordPress Automation System')
    parser.add_argument('--once', action='store_true', help='Run a single cycle and exit')
    args = parser.parse_args()

    # Inicializa o banco de dados para garantir que as tabelas existam
    try:
        db = Database()
        db.initialize()
        db.close()
        logger.info("Verificação do banco de dados concluída com sucesso.")
    except Exception as e:
        logger.critical(f"Falha crítica ao inicializar o banco de dados: {e}")
        return

    if args.once:
    except Exception as e:
        logger.critical(f"Critical error in scheduler: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
