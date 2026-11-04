-- The queries of the migration notes of the upgrade from 43 to dev, the next major, each must
-- return no rows. See https://github.com/dhis2/dhis2-releases/blob/master/releases/2.44/migration-notes.md

-- Tracked entity value has encrypted value but no plain text value: the migration fails on it.
select trackedentityid, trackedentityattributeid
from trackedentityattributevalue
where encryptedvalue is not null
  and (value is null or value = '');

-- Notes without an enrollment or event, which the migration moves into inconsistentnote. The
-- tables these two read are gone once 43 is 2.43.3 or later, whose V2_43_70 runs the same
-- migration: then drop them here, where they fail.
select n.uid
from note n
where not exists (select 1 from enrollment_notes l where l.noteid = n.noteid)
  and not exists (select 1 from trackerevent_notes l where l.noteid = n.noteid)
  and not exists (select 1 from singleevent_notes l where l.noteid = n.noteid);

-- Notes linked to more than one enrollment or event, on which the migration fails.
select noteid
from (
    select noteid from enrollment_notes
    union all
    select noteid from trackerevent_notes
    union all
    select noteid from singleevent_notes
) l
group by noteid
having count(*) > 1;
