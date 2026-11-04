-- The queries of the upgrade from 43.0 to 43, each must return no rows. The 2.43 notes are of
-- 43.0's migrations but Notes, which 2.43.3 adds; V2_43_69 fails with hints the notes do not list.
-- See https://github.com/dhis2/dhis2-releases/blob/master/releases/2.43/migration-notes.md

-- V2_43_69 makes organisationunit.path and hierarchylevel generated from a path array, and fails
-- on a view of organisationunit.
select c.relname
from pg_depend d
join pg_rewrite w on w.oid = d.objid
join pg_class c on c.oid = w.ev_class
where d.refclassid = 'pg_class'::regclass
  and d.classid = 'pg_rewrite'::regclass
  and d.refobjid = 'organisationunit'::regclass
  and c.relkind in ('v', 'm');

-- V2_43_69 fails on a cycle in the hierarchy, or a parent that does not exist.
with recursive walk (organisationunitid, parentid, seen) as (
    select organisationunitid, parentid, array[organisationunitid]
    from organisationunit
    union all
    select w.organisationunitid, o.parentid, w.seen || o.organisationunitid
    from walk w
    join organisationunit o on o.organisationunitid = w.parentid
    where o.organisationunitid <> all (w.seen)
)
select organisationunitid from walk
where parentid = any (seen)
union all
select o.organisationunitid
from organisationunit o
left join organisationunit p on p.organisationunitid = o.parentid
where o.parentid is not null and p.organisationunitid is null;

-- Notes without an enrollment or event, for 2.43.3 and later, whose V2_43_70 moves them into
-- inconsistentnote: see the 2.44 notes.
select n.uid
from note n
where not exists (select 1 from enrollment_notes l where l.noteid = n.noteid)
  and not exists (select 1 from trackerevent_notes l where l.noteid = n.noteid)
  and not exists (select 1 from singleevent_notes l where l.noteid = n.noteid);

-- Notes linked to more than one enrollment or event, on which V2_43_70 fails: see the 2.44 notes.
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
