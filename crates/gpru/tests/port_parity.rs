use gpru::{
    append_timestamp, deepget, dict_all_paths, dict_from_yml, now_str, prepend_datestamp,
    pretty_timedelta, safe_float, safe_int, safe_list,
};
use serde_yaml::{Mapping, Value};
use tempfile::tempdir;

#[test]
fn safe_types_work() {
    assert_eq!(
        safe_float(Some(&Value::String("22.5°c".into())), f64::NAN),
        22.5
    );
    assert_eq!(safe_int(Some(&Value::String("42".into())), 0), 42);
    assert_eq!(
        safe_list(Some(&Value::String("x".into()))),
        vec![Value::String("x".into())]
    );
}

#[test]
fn deepget_nested_paths() {
    let mut c = Mapping::new();
    c.insert(Value::String("c".into()), Value::Number(42.into()));
    let mut b = Mapping::new();
    b.insert(Value::String("b".into()), Value::Mapping(c));
    let mut a = Mapping::new();
    a.insert(Value::String("a".into()), Value::Mapping(b));

    assert_eq!(deepget("a/b/c", &a), Some(Value::Number(42.into())));
    assert!(dict_all_paths(&a).contains(&"a/b/c".to_string()));
}

#[test]
fn yaml_include_works() {
    let dir = tempdir().unwrap();
    let included = dir.path().join("included.yaml");
    std::fs::write(&included, "host: db.example.com\nport: 5432\n").unwrap();
    let main = dir.path().join("main.yaml");
    std::fs::write(&main, "app: myapp\ndb: !include included.yaml\n").unwrap();

    let loaded = dict_from_yml(&main).unwrap();
    let db = loaded.get(Value::String("db".into())).unwrap();
    match db {
        Value::Mapping(m) => {
            assert_eq!(
                m.get(Value::String("host".into())),
                Some(&Value::String("db.example.com".into()))
            );
        }
        _ => panic!("db should be mapping"),
    }
}

#[test]
fn time_helpers_format() {
    assert!(regex::Regex::new(r"^\d{8}\.\d{6}$")
        .unwrap()
        .is_match(&now_str()));
    assert!(pretty_timedelta(gpru::now_ts() - 10.0).contains('s'));

    let p = prepend_datestamp("/tmp/file.txt", " ");
    assert!(p
        .file_name()
        .unwrap()
        .to_string_lossy()
        .contains("file.txt"));

    let a = append_timestamp("/tmp/file.txt");
    assert!(a.file_name().unwrap().to_string_lossy().contains("file-"));
}
