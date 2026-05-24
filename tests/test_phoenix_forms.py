from pathlib import Path

from phoenix_helper.phoenix.forms import parse_upload_form


def test_parse_saved_upload_form() -> None:
    html = Path("上传页面.html").read_text(encoding="utf-8")

    form = parse_upload_form(html, "http://phoenix.stu.edu.cn")

    assert form.title_field.endswith("txtName")
    assert form.subtitle_field.endswith("txtNameExtra")
    assert form.description_field.endswith("txtDescription")
    assert form.file_field.endswith("fuFile")
    assert form.category_field.endswith("ddlCategory")
    assert form.tags_field is not None and form.tags_field.endswith("txtTags")
    assert "__VIEWSTATE" in form.fields
    assert "__EVENTVALIDATION" in form.fields
