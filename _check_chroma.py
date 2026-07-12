import sys
sys.path.insert(0, "backend")
from app.rag.chroma_store import all_ids
ids = all_ids()
print("Chroma collection size:", len(ids))
check = [
    ("275e1cd0-7c05-4919-a650-febef7e628ad", "VOM FEISTEN concert Fundbureau"),
    ("66cf7166-14ee-4f1d-8080-821c94d11c5b", "VOM FEISTEN party Fundbureau"),
    ("9184256d-ff8b-45ba-a6b9-09df868ad9e1", "subspAce Rote Flora"),
    ("b1cec2ab-2b7e-4b73-81dc-6ee1bfd0e22e", "Tutto Prosecco Hafenbahnhof"),
    ("2d2877f1-b1ff-4dce-bbfc-a3b3004ddb23", "20->02 Beat Boutique"),
]
for eid, label in check:
    print(f"  [{'IN ' if eid in ids else 'OUT'}] {eid}  {label}")
