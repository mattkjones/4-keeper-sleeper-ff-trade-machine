import streamlit as st
import sleeper_api as api
import valuation_engine as val
import itertools
import random

# --- CONFIGURATION ---
LEAGUE_ID = "1340545918419607552"

st.set_page_config(page_title="Keeper Trade Calc", layout="wide", page_icon="🏈")

# --- SESSION STATE INITIALIZATION ---
if 'team_a_slots' not in st.session_state:
    st.session_state.team_a_slots = 1
if 'team_b_slots' not in st.session_state:
    st.session_state.team_b_slots = 1

def add_team_a_slot():
    if st.session_state.team_a_slots < 7:
        st.session_state.team_a_slots += 1

def add_team_b_slot():
    if st.session_state.team_b_slots < 7:
        st.session_state.team_b_slots += 1

# --- GLOBAL DATA LOADING ---
@st.cache_data(ttl=3600)
def load_league_data(league_id):
    league = api.get_league_info(league_id)
    users = api.get_users(league_id)
    rosters = api.get_rosters(league_id)
    traded_picks = api.get_traded_picks(league_id) 
    drafts = api.get_league_drafts(league_id) 
    return league, users, rosters, traded_picks, drafts

@st.cache_data(ttl=86400) 
def load_nfl_players():
    return api.get_all_nfl_players()

with st.spinner("Syncing with Sleeper & FantasyCalc..."):
    league_info, users, rosters, traded_picks, drafts = load_league_data(LEAGUE_ID)
    nfl_players = load_nfl_players()
    value_df = val.fetch_player_values()

# --- DATA PROCESSING ---
if league_info and users and rosters and nfl_players and not value_df.empty:
    
    sorted_global_players = value_df.sort_values(by="Value", ascending=False).reset_index(drop=True)
    keeper_cutoff_value = sorted_global_players.iloc[53]['Value'] if len(sorted_global_players) > 53 else 1500

    user_dict = {u.get('user_id'): u for u in users}
    roster_id_to_team_name = {}
    
    for roster in rosters:
        r_id = roster.get('roster_id')
        owner_id = roster.get('owner_id')
        formatted_name = f"Team {r_id}"
        if owner_id and owner_id in user_dict:
            user = user_dict[owner_id]
            u_metadata = user.get('metadata') or {}
            r_metadata = roster.get('metadata') or {}
            display_name = user.get('display_name')
            t_name = r_metadata.get('team_name') or u_metadata.get('team_name') or display_name
            formatted_name = f"{t_name} ({display_name})"
        roster_id_to_team_name[r_id] = formatted_name

    team_names = list(roster_id_to_team_name.values())
    team_names.sort()
    num_teams = len(team_names) # Dynamically identify league size (e.g. 12)
    
    roster_map = {name: {} for name in team_names}
    all_rostered_players = set()
    for roster in rosters:
        t_name = roster_id_to_team_name.get(roster.get('roster_id'))
        player_ids = roster.get('players') or []
        for pid in player_ids:
            player_data = nfl_players.get(pid)
            if player_data:
                name = player_data.get('full_name') or f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
                if name:
                    roster_map[t_name][name] = pid
                    all_rostered_players.add(name)

    def get_position(player_name, team_name):
        pid = roster_map.get(team_name, {}).get(player_name)
        if pid and nfl_players.get(pid):
            pos = nfl_players[pid].get('position')
            if not pos:
                f_pos = nfl_players[pid].get('fantasy_positions')
                if f_pos: pos = f_pos[0]
            return pos or 'UNK'
        return 'UNK'

    draft_pool_df = value_df[~value_df['Player'].isin(all_rostered_players)].sort_values(by="Value", ascending=False).reset_index(drop=True)
    draft_pool_values = draft_pool_df['Value'].tolist()

    team_picks = {name: [] for name in team_names}
    pick_values_dict = {}
    all_picks = []
    
    league_season = int(league_info.get('season', 2026))
    draft_rounds = 12 

    roster_id_to_slot = {}
    current_draft = None
    if drafts:
        active_draft_id = league_info.get('draft_id')
        current_draft = next((d for d in drafts if d.get('draft_id') == active_draft_id), None)
        if not current_draft:
            current_draft = next((d for d in drafts if d.get('season') == str(league_season)), None)

    if current_draft:
        if current_draft.get('draft_order'):
            user_to_slot = current_draft['draft_order']
            for roster in rosters:
                owner_id = roster.get('owner_id')
                if owner_id in user_to_slot:
                    roster_id_to_slot[roster.get('roster_id')] = int(user_to_slot[owner_id])
        if current_draft.get('slot_to_roster_id'):
            for slot_str, r_id in current_draft['slot_to_roster_id'].items():
                roster_id_to_slot[int(r_id)] = int(slot_str)

    for year in range(league_season, league_season + 3):
        for r in range(1, draft_rounds + 1):
            for rid in roster_id_to_team_name.keys():
                all_picks.append({"season": str(year), "round": r, "original_roster_id": rid, "current_owner_id": rid})

    for tp in traded_picks:
        for pick in all_picks:
            if pick["season"] == tp.get("season") and pick["round"] == tp.get("round") and pick["original_roster_id"] == tp.get("roster_id"):
                pick["current_owner_id"] = tp.get("owner_id")
                break

    team_picks_raw = {name: [] for name in team_names}
    for pick in all_picks:
        curr_owner_team = roster_id_to_team_name.get(pick["current_owner_id"])
        orig_owner_team = roster_id_to_team_name.get(pick["original_roster_id"])
        if curr_owner_team:
            season_val, round_val, orig_roster_id = int(pick['season']), int(pick['round']), pick["original_roster_id"]
            base_str = f"{season_val} Round {round_val}"
            
            # Default to true mid-round for unknown future picks
            slot_val, sort_slot = (num_teams // 2), 99
            
            if str(season_val) == str(league_season) and orig_roster_id in roster_id_to_slot:
                base_slot = roster_id_to_slot[orig_roster_id]
                
                # --- SNAKE DRAFT LOGIC ---
                if round_val % 2 == 0:
                    # Even Round: Reverse the slot
                    slot_val = num_teams - base_slot + 1
                else:
                    # Odd Round: Standard slot
                    slot_val = base_slot
                    
                sort_slot = slot_val
                base_str += f" ({round_val}.{slot_val:02d})"
                
            pick_str = base_str if pick["current_owner_id"] == pick["original_roster_id"] else f"{base_str} (via {orig_owner_team})"
            
            overall_pick_index = ((round_val - 1) * num_teams) + (slot_val - 1)
            if overall_pick_index < len(draft_pool_values):
                pick_values_dict[pick_str] = draft_pool_values[overall_pick_index]
            else:
                pick_values_dict[pick_str] = 50

            team_picks_raw[curr_owner_team].append({"label": pick_str, "season": season_val, "round": round_val, "slot": sort_slot})

    team_picks = {t: [p["label"] for p in sorted(picks, key=lambda x: (x["season"], x["round"], x["slot"]))] for t, picks in team_picks_raw.items()}

    def get_asset_value(asset_name):
        if asset_name in pick_values_dict: return pick_values_dict[asset_name]
        res = value_df[value_df['Player'] == asset_name]
        if not res.empty: return res.iloc[0]['Value']
        return 0

    # --- PAGE 1: HOME PAGE (DASHBOARD) ---
    def render_home_page():
        st.title("🏠 My Team Dashboard")
        st.markdown("Analyze your roster, view your draft capital, and find dynamic multi-asset trade opportunities.")
        
        my_team = st.selectbox("Select Your Team:", team_names, index=0)
        st.divider()
        
        my_players = list(roster_map.get(my_team, {}).keys())
        my_player_data = [{"Player": p, "Value": get_asset_value(p), "Pos": get_position(p, my_team)} for p in my_players]
        my_player_data = sorted(my_player_data, key=lambda x: x['Value'], reverse=True)
        
        keepers = my_player_data[:4]
        trade_block = my_player_data[4:]
        my_picks = [{"Player": p, "Value": get_asset_value(p), "Pos": "PICK"} for p in team_picks.get(my_team, [])]
        
        col1, col2, col3 = st.columns([1.5, 1.2, 1])
        
        with col1:
            st.subheader("🛡️ Projected Keepers")
            if keepers:
                for k in keepers:
                    pid = roster_map[my_team].get(k['Player'])
                    c1, c2 = st.columns([1, 4])
                    with c1:
                        if pid:
                            st.image(f"https://sleepercdn.com/content/nfl/players/{pid}.jpg", width=50)
                    with c2:
                        st.markdown(f"**{k['Player']}** ({k['Pos']})")
                        st.caption(f"Value: {k['Value']:,}")
            else:
                st.write("No players.")
                
        with col2:
            st.subheader("📋 Full Bench")
            if trade_block:
                for b in trade_block:
                    st.markdown(f"{b['Player']} ({b['Pos']}) — *{b['Value']:,}*")
            else:
                st.write("No bench players.")

        with col3:
            st.subheader("📦 Draft Capital")
            if my_picks:
                for pick in my_picks:
                    st.markdown(f"📜 {pick['Player']} — *{pick['Value']:,}*")
            else:
                st.write("No draft picks owned.")
                
        st.divider()
        
        # --- THE MULTI-ASSET AI ENGINE ---
        ai_col_title, ai_col_btn = st.columns([4, 1])
        with ai_col_title:
            st.subheader("🤖 AI Package Trade Generator")
        with ai_col_btn:
            st.button("🔄 Refresh Trades", use_container_width=True)

        phase = st.radio("Strategic Focus:", ["🌴 Offseason (Consolidate depth into elite Keepers)", "🏈 In-Season (Liquidate elites for depth/picks)"], horizontal=True)
        is_offseason = "Offseason" in phase

        st.markdown("*Note: The AI applies a 'Consolidation Tax' (10-15% penalty) to the team trading away more assets, ensuring realistic package deals.*")

        suggestions = []
        seen_trades = set() 

        def get_packages(asset_list, max_items=3):
            combos = []
            for r in range(1, max_items + 1):
                for c in itertools.combinations(asset_list, r):
                    raw_val = sum([item['Value'] for item in c])
                    tax_multiplier = 1.0 if r == 1 else (0.90 if r == 2 else 0.85)
                    taxed_val = raw_val * tax_multiplier
                    names = [item['Player'] for item in c]
                    combos.append({"assets": names, "full_assets": c, "raw_value": raw_val, "taxed_value": taxed_val, "count": r})
            return combos

        if is_offseason:
            viable_bench = [p for p in trade_block if p['Value'] >= keeper_cutoff_value]
            my_trade_pool = (keepers[-1:] if len(keepers)==4 else []) + viable_bench[:3] + my_picks[:2]
        else:
            my_trade_pool = keepers[:2] + trade_block[:2] + my_picks[:1]

        my_packages = get_packages(my_trade_pool, max_items=3)
        my_current_pos = [k['Pos'] for k in keepers]

        for other_team in team_names:
            if other_team == my_team: continue
            
            other_players = [{"Player": p, "Value": get_asset_value(p), "Pos": get_position(p, other_team)} for p in roster_map.get(other_team, {}).keys()]
            other_players = sorted(other_players, key=lambda x: x['Value'], reverse=True)
            other_keepers = other_players[:4]
            other_block = other_players[4:]
            other_picks = [{"Player": p, "Value": get_asset_value(p), "Pos": "PICK"} for p in team_picks.get(other_team, [])]
            
            if is_offseason:
                their_viable_bench = [p for p in other_block if p['Value'] >= keeper_cutoff_value]
                their_trade_pool = other_keepers[1:4] + their_viable_bench[:2] + other_picks[:2]
            else:
                their_trade_pool = other_keepers[:3] + other_block[:3] + other_picks[:1]

            their_packages = get_packages(their_trade_pool, max_items=3)

            for my_pkg in my_packages:
                for their_pkg in their_packages:
                    
                    diff = abs(my_pkg['taxed_value'] - their_pkg['taxed_value'])
                    if diff <= (my_pkg['taxed_value'] * 0.10):
                        if my_pkg['taxed_value'] < 1000: continue
                        
                        if is_offseason:
                            if my_pkg['count'] <= their_pkg['count']: continue
                        else:
                            if my_pkg['count'] >= their_pkg['count']: continue

                        if is_offseason:
                            my_incoming_players = [p for p in their_pkg['full_assets'] if p['Pos'] != 'PICK']
                            their_incoming_players = [p for p in my_pkg['full_assets'] if p['Pos'] != 'PICK']
                            
                            my_sim = [p for p in my_player_data if p['Player'] not in my_pkg['assets']] + my_incoming_players
                            my_sim = sorted(my_sim, key=lambda x: x['Value'], reverse=True)
                            my_new_top_4 = [p['Player'] for p in my_sim[:4]]
                            if not all(p['Player'] in my_new_top_4 for p in my_incoming_players):
                                continue 
                                
                            their_sim = [p for p in other_players if p['Player'] not in their_pkg['assets']] + their_incoming_players
                            their_sim = sorted(their_sim, key=lambda x: x['Value'], reverse=True)
                            their_new_top_4 = [p['Player'] for p in their_sim[:4]]
                            if not all(p['Player'] in their_new_top_4 for p in their_incoming_players):
                                continue

                        impact_score = my_pkg['taxed_value']
                        my_incoming_players_all = [p for p in their_pkg['full_assets'] if p['Pos'] != 'PICK']
                        
                        for p in my_incoming_players_all:
                            if p['Pos'] not in my_current_pos and p['Pos'] in ['RB', 'WR', 'TE', 'QB']:
                                impact_score += 1500 
                                
                        if my_incoming_players_all and len(keepers) == 4:
                            best_incoming_val = max(p['Value'] for p in my_incoming_players_all)
                            if best_incoming_val > keepers[3]['Value'] + 800:
                                impact_score += 2500 
                                
                        impact_score += random.randint(-500, 500)

                        trade_type = f"{my_pkg['count']}-for-{their_pkg['count']}"
                        send_str = " + ".join(my_pkg['assets'])
                        rec_str = " + ".join(their_pkg['assets'])
                        
                        trade_key = tuple(sorted(my_pkg['assets']) + ["|"] + sorted(their_pkg['assets']))
                        
                        if trade_key not in seen_trades:
                            seen_trades.add(trade_key)
                            logic = f"Consolidating into elite assets." if is_offseason else f"Liquidating elite asset for depth."
                            sug_text = f"**Trade with {other_team} [{trade_type}]:**\n* **You Send:** {send_str} *(Raw: {int(my_pkg['raw_value']):,})*\n* **You Receive:** {rec_str} *(Raw: {int(their_pkg['raw_value']):,})*\n*Logic: {logic}*"
                            
                            suggestions.append({
                                "text": sug_text,
                                "type": trade_type,
                                "impact": impact_score
                            })

        suggestions = sorted(suggestions, key=lambda x: x['impact'], reverse=True)
        final_suggestions = []
        seen_types = {}
        
        for sug in suggestions:
            t = sug['type']
            if seen_types.get(t, 0) < 2:
                final_suggestions.append(sug)
                seen_types[t] = seen_types.get(t, 0) + 1
            if len(final_suggestions) >= 6:
                break

        if final_suggestions:
            for sug in final_suggestions: 
                st.info(sug['text'])
        else:
            st.success("No suggested trades at this time.")

    # --- PAGE 2: TRADE CALCULATOR ---
    def render_trade_calculator():
        st.title("⚖️ The Trade Ledger")
        
        col1, col2 = st.columns(2)
        with col1:
            team_a = st.selectbox("Team A:", team_names, index=0, key="calc_team_a")
        with col2:
            team_b = st.selectbox("Team B:", team_names, index=1, key="calc_team_b")

        st.divider()

        team_a_player_names = sorted(list(roster_map.get(team_a, {}).keys()))
        team_b_player_names = sorted(list(roster_map.get(team_b, {}).keys()))
        team_a_assets = ["-- Select Asset --"] + team_a_player_names + team_picks.get(team_a, [])
        team_b_assets = ["-- Select Asset --"] + team_b_player_names + team_picks.get(team_b, [])

        trade_col1, trade_col2 = st.columns(2)
        team_a_offers, team_b_offers = [], []

        with trade_col1:
            st.subheader(f"{team_a} Sends:")
            for i in range(st.session_state.team_a_slots):
                choice = st.selectbox(f"A_{i}", team_a_assets, key=f"a_asset_{i}", label_visibility="collapsed")
                if choice != "-- Select Asset --":
                    team_a_offers.append(choice)
            if st.session_state.team_a_slots < 7:
                st.button("➕ Add Asset", key="add_a", on_click=add_team_a_slot)

        with trade_col2:
            st.subheader(f"{team_b} Sends:")
            for i in range(st.session_state.team_b_slots):
                choice = st.selectbox(f"B_{i}", team_b_assets, key=f"b_asset_{i}", label_visibility="collapsed")
                if choice != "-- Select Asset --":
                    team_b_offers.append(choice)
            if st.session_state.team_b_slots < 7:
                st.button("➕ Add Asset", key="add_b", on_click=add_team_b_slot)

        st.divider()
        
        a_has_dupes = len(team_a_offers) != len(set(team_a_offers))
        b_has_dupes = len(team_b_offers) != len(set(team_b_offers))
        
        if a_has_dupes or b_has_dupes:
            st.warning("⚠️ **Duplicate Assets Detected:** You have added the same asset multiple times. The calculator has automatically filtered them out to ensure accurate valuation.")
            team_a_offers = list(dict.fromkeys(team_a_offers))
            team_b_offers = list(dict.fromkeys(team_b_offers))

        st.markdown("### Evaluation")
        
        team_a_receives_total = sum([get_asset_value(asset) for asset in team_b_offers])
        team_b_receives_total = sum([get_asset_value(asset) for asset in team_a_offers])

        eval_col1, eval_col2, eval_col3 = st.columns([1, 1, 1])
        
        diff = abs(team_a_receives_total - team_b_receives_total)
        
        if diff > 0:
            winner = team_a if team_a_receives_total > team_b_receives_total else team_b
            loser = team_b if team_a_receives_total > team_b_receives_total else team_a
        else:
            winner = "None"
            loser = "None"

        with eval_col1:
            st.metric(label=f"{team_a} Receives", value=f"{team_a_receives_total:,}")
            for p in team_b_offers:
                pid = roster_map[team_b].get(p)
                if pid:
                    st.image(f"https://sleepercdn.com/content/nfl/players/{pid}.jpg", width=70, caption=p)
                else:
                    st.caption(f"📜 {p} ({get_asset_value(p):,} pts)")

        with eval_col2:
            st.metric("Difference", f"{diff:,}")
            if diff > 0:
                st.markdown(f"**Favor:** {winner}")

        with eval_col3:
            st.metric(label=f"{team_b} Receives", value=f"{team_b_receives_total:,}")
            for p in team_a_offers:
                pid = roster_map[team_a].get(p)
                if pid:
                    st.image(f"https://sleepercdn.com/content/nfl/players/{pid}.jpg", width=70, caption=p)
                else:
                    st.caption(f"📜 {p} ({get_asset_value(p):,} pts)")

        st.write("") 
        
        if diff <= 250:
            st.success("🤝 **Analysis:** This trade is about as even as they get.")
        elif diff <= 750:
            st.info("⚖️ **Analysis:** This trade is pretty evenly balanced.")
        elif diff <= 1500:
            st.warning(f"⚠️ **Analysis:** This trade favors **{winner}**. **{loser}** should make sure they really feel good about the assets they are getting back in order to proceed.")
        else:
            st.error(f"🚨 **Analysis:** This trade heavily favors **{winner}**. **{loser}** is taking back significantly less capital than they are giving up, and should probably try to get some more assets back.")

    # --- SIDEBAR ROUTING ---
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to:", ["🏠 My Team", "⚖️ Trade Calculator"])

    if page == "🏠 My Team":
        render_home_page()
    else:
        render_trade_calculator()

else:
    st.error("Could not load data. Please check your connection and League ID.")