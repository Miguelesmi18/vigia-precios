from vigia import stores


def test_classify_shops():
    assert stores.classify("Amazon.es") == stores.RETAILER
    assert stores.classify("MediaMarkt") == stores.RETAILER
    assert stores.classify("El Corte Inglés") == stores.RETAILER
    assert stores.classify("eBay - superofertas") == stores.MARKETPLACE
    assert stores.classify("AliExpress") == stores.MARKETPLACE
    assert stores.classify("De'Longhi") == stores.OFFICIAL
    assert stores.classify("Tienda Rara 24") == stores.UNKNOWN


def test_whole_words_only():
    # "game" (la tienda GAME) no debe coincidir dentro de otra palabra
    assert stores.classify("Gameseal") == stores.UNKNOWN
    assert stores.classify("GAME") == stores.RETAILER


def test_second_hand_detection():
    assert stores.looks_second_hand("Cafetera X - Reacondicionado")
    assert stores.looks_second_hand("Cafetera X", "Producto usado")
    assert not stores.looks_second_hand("Cafetera X nueva", None)
