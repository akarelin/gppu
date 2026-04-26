use gpru::{Y2Eid, Y2List, Y2Path, Y2Slug, Y2Topic};

#[test]
fn y2list_basic() {
    let yl = Y2List::new(Some("hello_world_123"));
    assert_eq!(yl.data, vec!["hello", "world", "123"]);
    assert_eq!(yl.head(), Some("hello"));
    assert_eq!(yl.tail(), Some("123"));
}

#[test]
fn y2path_and_topic() {
    let yp = Y2Path::new(&["mqtt/sensors", "temp"]);
    assert_eq!(yp.to_string(), "mqtt/sensors/temp");

    let wildcard = Y2Topic::new("mqtt/+/temp");
    assert!(wildcard.is_wildcard());
    let non_wild = Y2Topic::new("mqtt/sensors/temp");
    assert!(!non_wild.is_wildcard());
}

#[test]
fn y2slug_and_eid() {
    let ys = Y2Slug::new("living_room@yala");
    assert_eq!(ys.to_string(), "living_room");

    let eid = Y2Eid::parse("light.living_room@yala").unwrap();
    assert_eq!(eid.domain, "light");
    assert_eq!(eid.ns, "yala");
    assert_eq!(eid.entity_id(), "light.living_room");
    assert_eq!(eid.to_string(), "light.living_room@yala");

    let defaulted = Y2Eid::parse("kitchen").unwrap();
    assert_eq!(defaulted.to_string(), "entity.kitchen@yala");
}
