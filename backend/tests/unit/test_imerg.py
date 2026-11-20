from app.services import imerg_service as im

SAMPLE = """Dataset: x
precipitation.lat, 10.35, 10.45
precipitation.precipitation[precipitation.time=16750][precipitation.lon=106.65], 1.385, -9999.9
precipitation.precipitation[precipitation.time=16750][precipitation.lon=106.75], 1.07, 1.77
lon, 106.65, 106.75
"""


def test_parse_ascii_and_grid_index():
    g = im.parse_ascii(SAMPLE)
    assert g == {(106.65, 10.35): 1.385, (106.75, 10.35): 1.07, (106.75, 10.45): 1.77}  # bỏ giá trị thiếu
    assert (im._idx(106.35, im.LON0), im._idx(10.35, im.LAT0)) == (2863, 1003)  # khớp chỉ số đã kiểm với OPeNDAP
