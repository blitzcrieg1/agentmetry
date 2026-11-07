"""Which email domains belong to public mailbox providers, for the Identity page.

"Personal" means the domain is a known public provider. "Corporate" means only
that it is not on this list, so somebody's own domain reads as corporate, and a
new or obscure provider does too. No list like this is ever complete. It labels
a reported domain for a person to look at, and proves nothing about who used it.
"""

from __future__ import annotations

#: Providers that use one name across many country domains: yahoo.fr, gmx.at,
#: hotmail.co.uk. Matched only on a plain country ending, so that
#: outlook.company.com does not read as personal.
_PROVIDER_NAMES = frozenset({"gmx", "hotmail", "outlook", "yahoo", "yandex"})

#: Second-level endings used before a country code, as in co.uk and com.br.
_SECOND_LEVEL = frozenset({"co", "com", "ne", "or"})

PERSONAL_DOMAINS = frozenset(
    {
        # Google
        "gmail.com",
        "googlemail.com",
        # Microsoft
        "live.at", "live.be", "live.ca", "live.cl", "live.cn", "live.co.kr", "live.co.uk", "live.co.za",
        "live.com", "live.com.ar", "live.com.au", "live.com.mx", "live.de", "live.dk", "live.fi", "live.fr",
        "live.ie", "live.in", "live.it", "live.jp", "live.nl", "live.no", "live.ru", "live.se",
        "msn.com",
        "passport.com",
        "windowslive.com",
        # Yahoo and its older brands
        "aim.com", "aol.co.uk", "aol.com", "aol.de", "aol.fr", "love.com", "rocketmail.com", "verizon.net",
        "wow.com", "ygm.com", "ymail.com",
        # Apple
        "icloud.com", "mac.com", "me.com",
        # Privacy-focused
        "duck.com", "mailbox.org", "pm.me", "posteo.at", "posteo.ch", "posteo.de", "posteo.net", "posteo.org",
        "proton.me", "protonmail.ch", "protonmail.com", "runbox.com", "simplelogin.com", "skiff.com",
        "startmail.com", "tuta.com", "tuta.io", "tutamail.com", "tutanota.com", "tutanota.de",
        # Global webmail
        "bk.ru", "email.com", "fastmail.com", "fastmail.fm", "hey.com", "hushmail.com", "inbox.com",
        "inbox.lv", "inbox.ru", "list.ru", "lycos.com", "mail.com", "mail.ru", "rambler.ru", "rediffmail.com",
        "usa.com", "ya.ru", "zoho.com", "zoho.eu", "zohomail.com", "zohomail.eu",
        # China, Korea, Japan
        "126.com", "139.com", "163.com", "188.com", "aliyun.com", "daum.net", "foxmail.com", "hanmail.net",
        "kakao.com", "nate.com", "naver.com", "qq.com", "sina.cn", "sina.com", "sohu.com", "tom.com",
        "vip.163.com", "vip.qq.com", "yeah.net",
        # Europe
        "alice.it", "arcor.de", "centrum.cz", "email.cz", "free.fr", "freenet.de", "gazeta.pl", "gmx.com", "gmx.net",
        "interia.pl", "laposte.net", "libero.it", "o2.pl", "onet.pl", "orange.fr", "seznam.cz", "sfr.fr",
        "t-online.de", "tiscali.it", "virgilio.it", "wanadoo.fr", "web.de", "wp.pl",
        # Greece
        "cosmote.net", "forthnet.gr", "hol.gr", "in.gr", "otenet.gr", "pathfinder.gr", 
        "yahoo.gr",
        # United Kingdom, North America, Australia
        "att.net", "bellsouth.net", "bigpond.com", "bigpond.net.au", "btinternet.com", "charter.net",
        "comcast.net", "cox.net", "earthlink.net", "ntlworld.com", "optonline.net", "optusnet.com.au",
        "rogers.com", "sbcglobal.net", "shaw.ca", "sky.com", "telus.net", "virginmedia.com",
        # Latin America, India, elsewhere
        "bol.com.br", "ig.com.br", "terra.com", "terra.com.br", "uol.com.br",
    }
)


def _is_country_ending(labels: list[str]) -> bool:
    if len(labels) == 1:
        return labels[0] == "com" or (len(labels[0]) == 2 and labels[0].isalpha())
    if len(labels) == 2:
        return labels[0] in _SECOND_LEVEL and len(labels[1]) == 2 and labels[1].isalpha()
    return False


def is_personal_domain(domain: str) -> bool:
    """Whether a reported domain is a known public mailbox provider."""
    value = domain.strip().lower().rstrip(".")
    if not value:
        return False
    labels = value.split(".")
    # A subdomain of a listed provider still belongs to it. A look-alike does not.
    if any(".".join(labels[i:]) in PERSONAL_DOMAINS for i in range(len(labels))):
        return True
    return labels[0] in _PROVIDER_NAMES and _is_country_ending(labels[1:])


def account_kind(domain: str) -> str:
    """`personal`, `corporate`, or `unclassified` when no domain was reported."""
    if not domain:
        return "unclassified"
    return "personal" if is_personal_domain(domain) else "corporate"
