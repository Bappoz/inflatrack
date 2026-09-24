import duckdb

conn = duckdb.connect("data/inflatrack.duckdb")

print("--- Ativos Diários (WTI, Brent, Gás Natural) ---")
df_daily = conn.execute("SELECT * FROM vw_features_daily ORDER BY data_referencia DESC LIMIT 5").df()
print(df_daily)
print("\n")

print("--- Ativos Mensais (Trigo, Milho, Algodão, Açúcar, Café, Índice Global) ---")
df_monthly = conn.execute("SELECT * FROM vw_features_monthly ORDER BY data_referencia DESC LIMIT 5").df()
print(df_monthly)
