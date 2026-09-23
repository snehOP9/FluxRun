import logging
import time
from redis import Redis
from fluxrun_api.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    client.ping()
    logging.info("FluxRun worker started; no durable job types are enabled before Milestone 2.")
    while True:
        time.sleep(30)
        client.ping()


if __name__ == "__main__":
    main()

