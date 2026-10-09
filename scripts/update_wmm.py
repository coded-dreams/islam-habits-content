"""Brings magnetic-model.json up to NOAA's latest World Magnetic Model release.

Prefers the high-resolution World Magnetic Model (WMMHR, degree 133) - NOAA's more detailed and
accurate version, recommended for systems that can carry it - and falls back to the standard WMM
(degree 12) only when no high-resolution release of at least the same epoch can be found.

Finding the files: NOAA's WMM coefficients page links the standard WMMyyyyCOF.zip directly; the
WMMHR zip sits behind a survey page, but NOAA has published it alongside the standard one under
the same /sites/default/files/<yyyy-mm>/ folder, so that folder (and the months around it) is
probed for WMMHRyyyyCOF.zip.

Each candidate's WMM.COF must reproduce the NOAA test values shipped inside its own zip before it
is used. Writes only when something changed. Exit code 0 for "updated" and "already current"
alike, non-zero on any failure (the workflow then opens an issue and the live file stays as is).
If the standard model had to be used even though a high-resolution one was expected, a note is
written to changes.md so the workflow raises an issue.
"""
import io
import os
import re
import urllib.error
import urllib.request
import zipfile

import calcdata
import wmm

WMM_PAGE = "https://www.ncei.noaa.gov/products/world-magnetic-model/wmm-coefficients"
HR_PAGE = "https://www.ncei.noaa.gov/products/world-magnetic-model-high-resolution"
FILES = "https://www.ncei.noaa.gov/sites/default/files"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (islam-habits-content-updater; +https://github.com/coded-dreams/islam-habits-content)"
}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as r:
        return r.read()


def exists(url):
    try:
        request = urllib.request.Request(url, headers=HEADERS, method="HEAD")
        with urllib.request.urlopen(request, timeout=60) as r:
            return r.status == 200
    except urllib.error.URLError:
        return False


def zip_links(page):
    html = fetch(page).decode("utf-8", "replace")
    return set(re.findall(r'(https://www\.ncei\.noaa\.gov/[^"\']*?WMM(?:HR)?\d{4}(?:v\d+)?COF\.zip)', html))


def year_of(url):
    return int(re.search(r"WMM(?:HR)?(\d{4})", url).group(1))


def hr_candidates(standard_urls):
    """WMMHR zip URLs worth trying, newest year first."""
    found = {u for u in zip_links(HR_PAGE) if "WMMHR" in u}
    for url in standard_urls:
        # Same folder as the standard release.
        found.add(re.sub(r"/WMM(\d{4})", r"/WMMHR\1", url))
        # NOAA has re-posted files a month or two later; probe the release window too.
        year = year_of(url)
        for folder in [f"{year - 1}-{m:02d}" for m in (10, 11, 12)] + [f"{year}-{m:02d}" for m in (1, 2, 3)]:
            found.add(f"{FILES}/{folder}/WMMHR{year}COF.zip")
    return sorted(found, key=lambda u: (-year_of(u), u))


def load_model(url):
    archive = zipfile.ZipFile(io.BytesIO(fetch(url)))
    names = archive.namelist()
    cofs = [n for n in names if n.upper().endswith(".COF")]
    cof_name = next((n for n in cofs if os.path.basename(n).upper() in ("WMM.COF", "WMMHR.COF")), cofs[0])
    test_name = next(n for n in names if re.search(r"test_?values\.txt$", n, re.I))
    epoch, name, rows = wmm.parse_cof(archive.read(cof_name).decode("ascii", "replace"))
    model = {
        "name": name,
        "epoch": epoch,
        "source": url,
        "coefficients": rows,
        "testValues": wmm.parse_test_values(archive.read(test_name).decode("ascii", "replace")),
    }
    if not wmm.reproduces(model):
        raise ValueError(f"{name} from {url} does not reproduce its own test values")
    return model


def main():
    standard_urls = sorted({u for u in zip_links(WMM_PAGE) if "WMMHR" not in u}, key=year_of, reverse=True)
    if not standard_urls:
        raise SystemExit("no standard WMM coefficient zip linked from " + WMM_PAGE)
    newest_year = year_of(standard_urls[0])

    chosen, note = None, None
    for url in hr_candidates(standard_urls[:1]):
        if year_of(url) < newest_year or not exists(url):
            continue
        try:
            chosen = load_model(url)
            break
        except (ValueError, zipfile.BadZipFile, StopIteration, IndexError) as e:
            note = f"- High-resolution candidate {url} was rejected: {e}"
    if chosen is None:
        chosen = load_model(standard_urls[0])
        note = (note or "") + (
            f"\n- No usable WMMHR{newest_year} was found next to the standard WMM{newest_year}, so the"
            " standard model was used. The app works fine on it; check NOAA's WMMHR page and the"
            " probe list in scripts/update_wmm.py."
        )

    data = calcdata.load(calcdata.MODEL_PATH)
    old = data.get("wmm") or {}
    if old.get("coefficients") == chosen["coefficients"] and old.get("epoch") == chosen["epoch"]:
        print(f"Magnetic model already current: {chosen['name']}")
    else:
        # Never trade a high-resolution model for a standard one of the same or an older epoch.
        if "HR" in old.get("name", "") and "HR" not in chosen["name"] and chosen["epoch"] <= old.get("epoch", 0):
            print(f"Kept {old['name']}: only the standard {chosen['name']} was found")
        else:
            data["wmm"] = chosen
            calcdata.write(calcdata.MODEL_PATH, data)
            print(f"Magnetic model updated: {old.get('name', 'none')} -> {chosen['name']}")
    if note:
        with open(os.path.join(calcdata.ROOT, "changes.md"), "a", encoding="utf-8") as f:
            f.write("Magnetic model update notes:\n" + note.strip() + "\n")


if __name__ == "__main__":
    main()
