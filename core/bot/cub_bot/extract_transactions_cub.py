import pandas as pd
import re

file_path = "statement.csv"

# ---- READ CSV WITH PIPE DELIMITER ----
df = pd.read_csv(
    file_path,
    engine="python",
    sep="|",  # CSV uses pipe delimiter
    on_bad_lines="skip"
)

# Normalize column names
df.columns = df.columns.str.lower().str.strip()

# ---- FILTER ONLY CREDIT TRANSACTIONS ----
# Filter rows where CR column has a value (not empty/NaN)
df = df[df["cr"].notna() & (df["cr"].astype(str).str.strip() != "")]

# ---- EXTRACT UTR ----
def extract_utr(description):
    if not isinstance(description, str):
        return None
    
    # Pattern 1: For NEFT transactions - UTR:XXXXXXXXXX
    neft_match = re.search(r"UTR:([A-Z0-9]+)", description)
    if neft_match:
        return neft_match.group(1)
    
    # Pattern 2: For UPI transactions - UPI/CR/XXXXXXXXXXXX
    upi_match = re.search(r"UPI/CR/(\d{12})", description)
    if upi_match:
        return upi_match.group(1)
    
    return None

df["UTR"] = df["description"].apply(extract_utr)

# ---- CLEAN AMOUNT (remove commas) ----
df["Amount"] = df["cr"].str.replace(",", "").astype(float)

# ---- FINAL RESULT ----
result = df[["UTR", "Amount"]].dropna()

print("\n=== CR Transactions with UTR and Amount ===")
print(result)
print(f"\nTotal CR transactions found: {len(result)}")

# Save output
result.to_csv("credit_utr_amount.csv", index=False)
print("\nOutput saved to: credit_utr_amount.csv")
