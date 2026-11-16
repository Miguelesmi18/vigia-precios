"""Objetos falsos para probar sin internet (se usan en varios tests)."""


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    """Imita requests.Session: devuelve las respuestas preparadas, en orden."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.responses.pop(0))

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)
