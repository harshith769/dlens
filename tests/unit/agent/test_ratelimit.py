from dlens.agent.llm.ratelimit import RPM_LIMITS, RateLimiter

from .conftest import FakeClock


def test_limits_table():
    assert RPM_LIMITS == {"gemini": 15, "groq": 30, "ollama": None}


def test_first_n_immediate_then_waits_exact_remainder():
    c = FakeClock()
    r = RateLimiter(15, c.seconds, c.sleep)
    for _ in range(15):
        r.acquire()
        c.advance(1)  # 15 calls over 15 s
    r.acquire()  # 16th: oldest was at t=0, now t=15 -> wait 45 s
    assert c.slept == [45.0]


def test_window_slides():
    c = FakeClock()
    r = RateLimiter(2, c.seconds, c.sleep)
    r.acquire()
    c.advance(30)
    r.acquire()
    c.advance(31)  # first call has left the window
    r.acquire()
    assert c.slept == []
    r.acquire()  # window now holds t=30 and t=61; next opens at t=90
    assert c.slept == [29.0]


def test_unlimited_never_sleeps():
    c = FakeClock()
    r = RateLimiter(None, c.seconds, c.sleep)
    for _ in range(1000):
        r.acquire()
    assert c.slept == []
