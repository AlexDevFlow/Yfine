"""Tests for the OFX parser using a hand-crafted sample."""
from services.importers.ofx_parser import OfxParser


_OFX_SAMPLE = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
<DTSERVER>20240115120000</DTSERVER><LANGUAGE>ENG</LANGUAGE></SONRS></SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><TRNUID>1001</TRNUID>
<STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
<STMTRS>
<CURDEF>USD</CURDEF>
<BANKACCTFROM><BANKID>123456</BANKID><ACCTID>987654321</ACCTID><ACCTTYPE>CHECKING</ACCTTYPE></BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20240101000000</DTSTART>
<DTEND>20240131235959</DTEND>
<STMTTRN>
<TRNTYPE>CREDIT</TRNTYPE>
<DTPOSTED>20240105120000</DTPOSTED>
<TRNAMT>1500.00</TRNAMT>
<FITID>TX001</FITID>
<NAME>Salary</NAME>
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20240106120000</DTPOSTED>
<TRNAMT>-45.20</TRNAMT>
<FITID>TX002</FITID>
<NAME>Grocery</NAME>
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>1454.80</BALAMT><DTASOF>20240131235959</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""


def test_ofx_sniff_accepts_ofx_header():
    assert OfxParser().sniff(_OFX_SAMPLE)
    assert not OfxParser().sniff(b"date,amount\n2024-01-01,1.00\n")


def test_ofx_parses_transactions():
    result = OfxParser().parse(_OFX_SAMPLE)
    assert len(result.movements) == 2
    in_mov = [m for m in result.movements if m.direction == "in"][0]
    out_mov = [m for m in result.movements if m.direction == "out"][0]
    assert in_mov.amount == 1500.0
    assert out_mov.amount == 45.2
    assert in_mov.external_ref == "TX001"
    assert result.detected_currency == "USD"
