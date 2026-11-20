from vigia import stores


def test_classify_shops():
    assert stores.classify("Amazon.es") == stores.RETAILER
    assert stores.classify("MediaMarkt") == stores.RETAILER
    assert stores.classify("El Corte Inglés") == stores.RETAILER
    assert stores.classify("eBay - superofertas") == stores.MARKETPLACE
    assert stores.classify("AliExpress") == stores.MARKETPLACE
    assert stores.classify("Alibaba.com") == stores.MARKETPLACE
    assert stores.classify("De'Longhi") == stores.OFFICIAL
    assert stores.classify("Tienda Rara 24") == stores.UNKNOWN


def test_whole_words_only():
    # "fnac" no debe coincidir dentro de otra palabra
    assert stores.classify("Fnacshop24") == stores.UNKNOWN
    assert stores.classify("Fnac") == stores.RETAILER


def test_only_your_trusted_shops_and_brands(monkeypatch):
    for shop in ["Amazon.es", "MediaMarkt", "El Corte Inglés", "Carrefour", "Fnac",
                 "PcComponentes", "delonghi.es", "Razer.com"]:
        assert stores.is_trusted(stores.classify(shop)), shop
    for shop in ["Worten", "makro.es", "Leroy Merlin España", "Amazon.es - Seller"]:
        assert not stores.is_trusted(stores.classify(shop)), shop
    monkeypatch.setenv("TRUSTED_SHOPS", "worten, fnac")       # cambiable en el .env
    assert stores.classify("Worten") == stores.RETAILER
    assert stores.classify("Carrefour") == stores.UNKNOWN


def test_second_hand_detection():
    assert stores.looks_second_hand("Cafetera X - Reacondicionado")
    assert stores.looks_second_hand("Cafetera X", "Producto usado")
    assert not stores.looks_second_hand("Cafetera X nueva", None)


def test_third_party_sellers_and_brands():
    assert stores.classify("Amazon.es - Seller") == stores.MARKETPLACE
    assert stores.classify("Amazon.es") == stores.RETAILER
    assert stores.classify("Razer.com") == stores.OFFICIAL
    assert stores.classify("delonghi.es") == stores.OFFICIAL


def test_foreign_shops():
    assert stores.is_foreign("coffeeone.com.ua")
    assert stores.is_foreign("ElektroshopWagner.de")
    assert stores.is_foreign("Play-Asia.com")
    assert not stores.is_foreign("PcComponentes")
    assert not stores.is_foreign("delonghi.es")
    assert "extranjera" in stores.describe("reichelt.de", stores.UNKNOWN)
