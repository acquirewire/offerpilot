"""Diagnose the Twilio 400: list account status, the From number's SMS
capability, and which destination numbers are verified."""
from src import config as config_mod
from twilio.rest import Client

s = config_mod.load()
c = Client(s.twilio_sid, s.twilio_token)

acct = c.api.accounts(s.twilio_sid).fetch()
print(f"Account type:   {acct.type}   (status={acct.status})")
print(f"Configured FROM: {s.twilio_from}")
print(f"Configured TO:   {s.sms_to}")

print("\n-- Twilio numbers you own --")
for n in c.incoming_phone_numbers.list(limit=20):
    print(f"  {n.phone_number}  sms_capable={n.capabilities.get('sms')}")

print("\n-- Verified caller IDs (trial can only text these) --")
ids = c.outgoing_caller_ids.list(limit=50)
if not ids:
    print("  (none verified)")
for v in ids:
    print(f"  {v.phone_number}")
