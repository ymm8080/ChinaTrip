import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    print('version', c.execute(text("select version_num from alembic_version")).scalar())
    print('drafts', c.execute(text("select count(*) from trip_items where draft_session_id is not null")).scalar())
    print('visible rows', c.execute(text("select count(*) from trip_items where draft_session_id is null and deletion_flag=false")).scalar())
    print('view count', c.execute(text("select count(*) from wish_items")).scalar())
