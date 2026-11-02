import threading
import time

from gesec.data.extract_pdf.orchestration import (
    init_pdf4llm_semaphore,
    pdf4llm_slot,
    reset_pdf4llm_semaphore,
)


def test_pdf4llm_slot_borne_la_concurrence():
    init_pdf4llm_semaphore(2)
    lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0

    def work() -> None:
        nonlocal in_flight, max_in_flight
        with pdf4llm_slot():
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(0.02)
            with lock:
                in_flight -= 1

    threads = [threading.Thread(target=work) for _ in range(6)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        reset_pdf4llm_semaphore()

    assert max_in_flight == 2


def test_pdf4llm_slot_sans_semaphore_ne_borne_pas():
    reset_pdf4llm_semaphore()
    with pdf4llm_slot():
        pass
