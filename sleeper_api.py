import requests

def get_league_info(league_id):
    """Fetches basic league metadata (name, settings, etc.)."""
    url = f"https://api.sleeper.app/v1/league/{league_id}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

def get_users(league_id):
    """Fetches all users (managers) in the league."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return []

def get_rosters(league_id):
    """Fetches current rosters, mapping player IDs to roster IDs."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return []

def get_all_nfl_players():
    """
    Fetches the master dictionary of all NFL players.
    Sleeper highly recommends caching this or only calling it once per day 
    as the JSON payload is roughly 5MB.
    """
    url = "https://api.sleeper.app/v1/players/nfl"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return {}

def get_traded_picks(league_id):
    """Fetches the ledger of all traded draft picks in the league."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/traded_picks"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return []

def get_league_drafts(league_id):
    """Fetches all drafts associated with the given league."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/drafts"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return []