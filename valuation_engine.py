import requests
import pandas as pd
import streamlit as st

@st.cache_data(ttl=3600)
def fetch_player_values():
    """Fetches Dynasty values and applies the Keeper Tier Curve."""
    # isDynasty=true (Dynasty Baseline)
    # numQbs=1 (Superflex OFF)
    # numTeams=12 (12-Team League)
    # ppr=0.5 (Half-PPR Scoring)
    url = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1&numTeams=12&ppr=0.5"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        players = []
        
        for item in data:
            player_info = item.get('player', {})
            name = player_info.get('name')
            value = item.get('value')
            
            if name and value is not None:
                players.append({
                    "Player": name,
                    "Raw_Value": int(value)
                })
                
        df = pd.DataFrame(players)
        
        # Sort by Raw_Value to establish the true Overall Rank
        df = df.sort_values(by="Raw_Value", ascending=False).reset_index(drop=True)
        df['Rank'] = df.index + 1
        
        # Apply the Custom Keeper Curve
        def apply_curve(row):
            val = row['Raw_Value']
            rank = row['Rank']
            
            if rank <= 12:
                return int(val * 1.20)  # +20% for Elite Keepers
            elif rank <= 24:
                return int(val * 1.10)  # +10% for Great Keepers
            elif rank <= 54:
                return int(val * 1.00)  # Base Value for bubble/draft pool
            elif rank <= 60:
                return int(val * 0.80)  # -20% Slash
            elif rank <= 66:
                return int(val * 0.65)  # -35% Slash
            else:
                return int(val * 0.50)  # -50% Slash for waiver fodder
                
        df['Value'] = df.apply(apply_curve, axis=1)
        
        return df
    else:
        st.error("Failed to fetch data from FantasyCalc.")
        return pd.DataFrame(columns=["Player", "Raw_Value", "Rank", "Value"])