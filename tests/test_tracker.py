import openpyxl

from jobagent.tracker import SHEET, Tracker

LINK = "https://www.linkedin.com/jobs/view/1/"


def test_web_text_starting_with_equals_is_stored_as_text(tmp_path):
    t = Tracker(tmp_path / "log.xlsx", tmp_path, print)
    t.add_row({"Company": '=HYPERLINK("http://evil","x")', "Title": "+1 dev", "Link": LINK})
    cell = openpyxl.load_workbook(tmp_path / "log.xlsx")[SHEET].cell(2, 2)
    assert cell.data_type == "s"
    assert cell.value == '=HYPERLINK("http://evil","x")'


def test_rows_and_history_survive_a_restart(tmp_path):
    t = Tracker(tmp_path / "log.xlsx", tmp_path, print)
    t.add_row({"Company": "Acme", "Title": "Dev", "Link": LINK})
    t.mark("linkedin:2", "low_fit")
    t.add_sent("linkedin")
    again = Tracker(tmp_path / "log.xlsx", tmp_path, print)
    assert again.seen("linkedin:1") and again.seen("linkedin:2")
    assert again.sent_today("linkedin") == 1
