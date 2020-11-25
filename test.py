from urllib.parse import parse_qs, urlparse
url = "https://cloudflare-ipfs.com/ipfs/bafk2bzaced2r3q7fk3vum7ufhjig7yntjhy7wyg7tiemxjs3fzpvzx5llc5ry?filename=Sachiaki%20Takamiya%20-%20Ikigai%20Diet_%20The%20Secret%20of%20Japanese%20Diet%20to%20Health%20and%20Longevity-Zen%20Quest%20%282018%29.epub"
print({k: v[0] if v and len(v) == 1 else v for k,
       v in parse_qs(urlparse(url).query).items()}["wow"])
