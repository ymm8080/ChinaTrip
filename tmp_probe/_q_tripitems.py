import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
q = """
select coalesce(itinerary_ref,'(null)') as ref, count(*) n,
       sum(case when itinerary_id is null then 1 else 0 end) fk_null,
       sum(case when deletion_flag then 1 else 0 end) deleted
from trip_items group by 1 order by n desc limit 40
"""
with eng.connect() as c:
    for r in c.execute(text(q)):
        print(r)
    print('---- itineraries count')
    print(c.execute(text("select count(*) from itineraries")).scalar())
    print('---- draft-ish refs not in itineraries')
    for r in c.execute(text("""
        select t.itinerary_ref, count(*) n
        from trip_items t
        where t.itinerary_ref is not null
          and t.deletion_flag = false
          and not exists (select 1 from itineraries i where i.itinerary_ref = t.itinerary_ref or i.id::text = t.itinerary_ref)
        group by 1 order by n desc limit 20
    """)):
        print(r)
