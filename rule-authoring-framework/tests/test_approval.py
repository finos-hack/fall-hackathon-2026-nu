import pytest
import yaml

from rule_authoring import approval as ap


class Store:
    def __init__(self, item):
        self.item = item

    def get_catalog_item(self, i, v=None):
        return self.item if self.item and self.item["id"] == i else None

    def upsert_catalog_item(self, item):
        self.item = item
        return item


def test_approve_draft_records_approver_and_time():
    s = Store({"id": "X", "status": "DRAFT"})
    out = ap.approve(s, "X", " alice ")
    assert out["status"] == "APPROVED" and out["approved_by"] == "alice" and out["approved_at"]


@pytest.mark.parametrize("item,by", [({"id": "X", "status": "APPROVED"}, "a"), ({"id": "X", "status": "DRAFT"}, " "),
                                     (None, "a")])
def test_approve_rejects(item, by):
    with pytest.raises(ap.ApprovalError):
        ap.approve(Store(item), "X", by)


def test_catalog_file_and_cli(tmp_path, capsys):
    cat = tmp_path / "controls.catalog.yaml"
    cat.write_text(yaml.safe_dump([{"control_id": "C1", "status": "DRAFT"}, {"control_id": "C2", "status": "DRAFT"}]),
                   encoding="utf-8")
    assert ap.main(["approve", "C1", "--by", "bob", "--catalog", str(cat)]) == 0
    data = yaml.safe_load(cat.read_text(encoding="utf-8"))
    assert data[0]["status"] == "APPROVED" and data[0]["approved_by"] == "bob" and data[1]["status"] == "DRAFT"
    assert ap.main(["approve", "C1", "--by", "bob", "--catalog", str(cat)]) == 1  # already approved
    assert ap.main(["approve", "NOPE", "--by", "bob", "--catalog", str(cat)]) == 1
