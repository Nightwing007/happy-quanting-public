// Display text for the backend's fee categories (see CATEGORIES in app/trading/fees.py).
export const CHARGE_CATEGORIES: { id: string; label: string; help: string }[] = [
  { id: "brokerage", label: "Brokerage", help: "What your broker charges for carrying out the trade." },
  { id: "tax", label: "Taxes", help: "Government transaction taxes and stamp duty. They are the same whichever broker you use." },
  { id: "exchange", label: "Exchange fees", help: "What the stock exchange charges for matching and clearing the trade." },
  { id: "regulatory", label: "Regulatory fees", help: "Small levies that fund the market regulator, such as SEBI in India or the SEC in the US." },
  { id: "depository", label: "Depository fees", help: "Charges for moving shares in and out of your demat account." },
  { id: "gst", label: "GST", help: "Goods and services tax on your broker's and exchange's service charges. It is not charged on transaction taxes." },
  { id: "fx", label: "Currency conversion", help: "The markup your broker adds when your cash has to change currency to buy or sell here." },
];
