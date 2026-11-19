from enum import StrEnum


class Bank(StrEnum):
    HSBC = "HSBC"
    AU = "AU"
    HDFC = "HDFC"
    ICICI = "ICICI"
    AXIS = "AXIS"
    AMEX = "AMEX"


class CardNetwork(StrEnum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    AMEX = "AMEX"
    RUPAY = "RUPAY"


class TransactionType(StrEnum):
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"
    FEE = "FEE"
    INTEREST = "INTEREST"
    REWARD = "REWARD"


class TransactionCategory(StrEnum):
    OTHER = "OTHER"
    SHOPPING = "SHOPPING"
    FOOD = "FOOD"
    TRAVEL = "TRAVEL"
    FUEL = "FUEL"
    GROCERY = "GROCERY"
    UTILITIES = "UTILITIES"
