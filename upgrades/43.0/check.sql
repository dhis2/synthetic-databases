-- The queries of the migration notes of the upgrade from 42.0 to 43.0, each must return no rows.
-- See https://github.com/dhis2/dhis2-releases/blob/master/releases/2.43/migration-notes.md

-- Null Occurred Date for Single Events: V2_43_21 moves single events into singleevent, whose
-- occurreddate is not null.
select ev.uid
from event ev
join programstage ps on ps.programstageid = ev.programstageid
join program p on p.programid = ps.programid
where ev.occurreddate is null
  and p.type = 'WITHOUT_REGISTRATION';

-- Inconsistent Events: V2_43_21 moves the events of a program stage without a program into
-- inconsistentevent, which the API does not read.
select ev.uid
from event ev
join programstage ps on ps.programstageid = ev.programstageid
where ps.programid is null;

-- Tracker Associate: V2_43_42 fails on the value type.
select uid from trackedentityattribute where valuetype = 'TRACKER_ASSOCIATE'
union all
select uid from dataelement where valuetype = 'TRACKER_ASSOCIATE';

-- Enrollment Attribute Option Combo: V2_43_45 fails on several category option combos named
-- default without one of the UID HllvX50cXC0.
select count(*)
from categoryoptioncombo
where name = 'default'
having count(*) > 1 and not bool_or(uid = 'HllvX50cXC0');
