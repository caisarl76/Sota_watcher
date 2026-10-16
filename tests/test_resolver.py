import pytest

from release_watcher.resolver import InvalidURL, resolve


@pytest.mark.parametrize("url,type_,norm,meta", [
    ("https://github.com/Owner/Repo", "github", "https://github.com/Owner/Repo", {"owner": "Owner", "repo": "Repo"}),
    ("github.com/x/y/tree/main/src", "github", "https://github.com/x/y", {"owner": "x", "repo": "y"}),
    ("https://www.github.com/x/y.git/", "github", "https://github.com/x/y", {"owner": "x", "repo": "y"}),
    ("https://huggingface.co/org/model", "huggingface", "https://huggingface.co/org/model",
     {"repo_id": "org/model", "hf_repo_type": "model"}),
    ("https://huggingface.co/datasets/org/ds/tree/main", "huggingface", "https://huggingface.co/datasets/org/ds",
     {"repo_id": "org/ds", "hf_repo_type": "dataset"}),
    ("https://arxiv.org/abs/2410.12345v2", "arxiv", "https://arxiv.org/abs/2410.12345", {"arxiv_id": "2410.12345"}),
    ("https://arxiv.org/pdf/2410.12345.pdf", "arxiv", "https://arxiv.org/abs/2410.12345", {"arxiv_id": "2410.12345"}),
    ("https://my-lab.github.io/project/#results", "project_page", "https://my-lab.github.io/project", {}),
])
def test_resolve(url, type_, norm, meta):
    r = resolve(url)
    assert (r.type, r.url, r.meta) == (type_, norm, meta)


@pytest.mark.parametrize("url", ["", "ftp://x.com/a", "https://github.com/x", "https://arxiv.org/list/cs.CV",
                                 "not a url"])
def test_invalid(url):
    with pytest.raises(InvalidURL):
        resolve(url)
