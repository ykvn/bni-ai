import json

def calculate_dormant_account_risk(days_inactive: int, account_balance: float, sudden_withdrawal_amount: float = 0.0) -> str:
    """
    Calculates an automated risk priority score and security flag for a dormant account
    based on inactivity duration, asset exposure, and suspicious transaction volume.
    """
    risk_score = 0
    factors = []
    
    # 1. Evaluate the base dormancy timeline factor
    if days_inactive >= 365:
        risk_score += 40
        factors.append("Severe Inactivity: Account dormant for over a year.")
    elif days_inactive >= 180:
        risk_score += 20
        factors.append("Standard Dormancy: Account inactive for over 180 days.")
        
    # 2. Evaluate financial exposure / high-balance target vulnerability
    if account_balance > 100000:
        risk_score += 30
        factors.append("High Asset Exposure: Balance exceeds $100,000 threshold.")
    elif account_balance > 50000:
        risk_score += 15
        factors.append("Moderate Asset Exposure: Balance exceeds $50,000 threshold.")
        
    # 3. Evaluate unexpected velocity or transactional spikes on cold accounts
    if sudden_withdrawal_amount > 0:
        if days_inactive >= 180:
            risk_score += 30
            factors.append(f"High-Risk Transaction: Sudden attempt to withdraw ${sudden_withdrawal_amount:,.2f} on a cold account.")
        else:
            risk_score += 10
            factors.append(f"Minor Velocity Shift: Transaction activity detected.")

    # 4. Determine final enterprise compliance categorization tier
    if risk_score >= 70:
        risk_tier = "CRITICAL RISK - IMMEDIATE HOLD ADVISED"
    elif risk_score >= 40:
        risk_tier = "HIGH RISK - REQUIRE MULTI-FACTOR VERIFICATION"
    elif risk_score >= 20:
        risk_tier = "MEDIUM RISK - MONITOR ACCOUNT CLOSELY"
    else:
        risk_tier = "LOW RISK - STANDARD COMPLIANCE PROFILE"
        
    evaluation_result = {
        "calculated_risk_score": min(risk_score, 100),
        "risk_classification_tier": risk_tier,
        "contributing_risk_factors": factors,
        "requires_intervention": risk_score >= 40
    }
    
    return json.dumps(evaluation_result, indent=2)