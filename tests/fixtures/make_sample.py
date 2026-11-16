"""Generate a synthetic sample in the same shape as the CFPB API response.

Used only for tests and CI so they run offline. Real numbers for your resume
must come from the live API, not from this file.
"""
import json
import random
from datetime import date, timedelta

random.seed(42)

PRODUCTS = {
    "Mortgage": ["my mortgage servicer lost my escrow payment", "loan modification was denied after months",
                 "foreclosure notice even though I paid", "the escrow account shortage raised my monthly payment"],
    "Credit card": ["charged a late fee on my credit card after I paid", "unauthorized charges on my card statement",
                    "credit limit was lowered without notice", "the card company would not refund a disputed purchase"],
    "Checking or savings account": ["overdraft fees on my checking account", "bank froze my savings account",
                                    "debit card deposit never posted to checking", "branch closed my account without warning"],
    "Credit reporting": ["incorrect information on my credit report", "the bureau will not remove an account that is not mine",
                         "my credit score dropped because of a reporting error", "dispute with the credit bureau ignored"],
    "Debt collection": ["collector keeps calling about a debt I do not owe", "debt collector threatened legal action",
                        "collection agency would not validate the debt", "calls at work from a collection agency"],
    "Student loan": ["student loan servicer misapplied my payment", "income driven repayment application lost",
                     "forbearance was not applied to my student loan", "servicer transferred my student loan without notice"],
}
COMPANIES = ["Northgate Bank", "Harbor Financial", "Summit Credit Union", "Pioneer Lending",
             "Granite Trust", "Lakeshore Bank", "Meridian Card Services", "Atlas Collections"]
STATES = ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI", None]
CHANNELS = ["Web", "Phone", "Referral", "Postal mail", "Fax"]
RESPONSES = ["Closed with explanation", "Closed with monetary relief",
             "Closed with non-monetary relief", "In progress", "Untimely response"]
FILLER = ["I contacted them several times.", "Nobody would help me.", "This has caused me a lot of stress.",
          "I have documentation of everything.", "I want this resolved.", ""]


def response_for(product: str) -> str:
    """Payouts are more likely for some products, so the classifier has a real pattern to find."""
    payout_chance = 0.30 if product in ("Credit card", "Checking or savings account") else 0.04
    if random.random() < payout_chance:
        return "Closed with monetary relief"
    return random.choice([r for r in RESPONSES if r != "Closed with monetary relief"])


def make(n: int = 3000):
    hits, start = [], date(2025, 1, 1)
    for i in range(n):
        product = random.choice(list(PRODUCTS))
        received = start + timedelta(days=random.randint(0, 600))
        narrative = None
        if random.random() < 0.7:   # like the real data, many complaints have no narrative
            narrative = f"{random.choice(PRODUCTS[product])}. {random.choice(FILLER)} {random.choice(FILLER)}".strip()
        hits.append({"_id": str(9000000 + i), "_source": {
            "complaint_id": str(9000000 + i),
            "date_received": received.isoformat() + "T12:00:00-05:00",
            "date_sent_to_company": (received + timedelta(days=random.randint(0, 5))).isoformat() + "T12:00:00-05:00",
            "product": product, "sub_product": None, "issue": random.choice(PRODUCTS[product])[:40],
            "sub_issue": None, "company": random.choice(COMPANIES), "state": random.choice(STATES),
            "zip_code": f"{random.randint(10000, 99999)}", "submitted_via": random.choice(CHANNELS),
            "company_response": response_for(product), "timely": random.choice(["Yes"] * 9 + ["No"]),
            "consumer_disputed": "N/A", "complaint_what_happened": narrative,
            "tags": random.choice([None, ["Older American"], ["Servicemember"]]),
        }})
    # A few bad rows on purpose, to show the quarantine working
    hits.append(json.loads(json.dumps(hits[0])))                                  # duplicate
    bad = json.loads(json.dumps(hits[1])); bad["_id"] = None; bad["_source"]["complaint_id"] = None
    hits.append(bad)                                                              # missing id
    bad = json.loads(json.dumps(hits[2])); bad["_id"] = bad["_source"]["complaint_id"] = "9999998"
    bad["_source"]["date_received"] = "2026-13-45"; hits.append(bad)              # invalid date
    bad = json.loads(json.dumps(hits[3])); bad["_id"] = bad["_source"]["complaint_id"] = "9999999"
    bad["_source"]["date_received"] = "2099-01-01T12:00:00-05:00"; hits.append(bad)  # future date
    return hits


if __name__ == "__main__":
    with open("tests/fixtures/sample_complaints.json", "w") as f:
        json.dump(make(), f)
