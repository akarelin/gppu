use serde_yaml::{Mapping, Value};
use std::collections::BTreeMap;

pub fn deepget(path: &str, data: &Mapping) -> Option<Value> {
    if data.contains_key(Value::String(path.to_string())) {
        return data.get(Value::String(path.to_string())).cloned();
    }

    let mut cur = Value::Mapping(data.clone());
    for part in path.split('/') {
        cur = match cur {
            Value::Mapping(m) => m.get(Value::String(part.to_string())).cloned()?,
            _ => return None,
        };
    }
    Some(cur)
}

pub fn dict_all_paths(data: &Mapping) -> Vec<String> {
    let mut result = Vec::new();
    for (k, v) in data {
        if let Value::String(key) = k {
            result.push(key.clone());
            if let Value::Mapping(inner) = v {
                for p in dict_all_paths(inner) {
                    result.push(format!("{key}/{p}"));
                }
            }
        }
    }
    result
}

pub fn dict_sort_keylen(data: &Mapping, reverse: bool) -> BTreeMap<String, Value> {
    let mut pairs: Vec<(String, Value)> = data
        .iter()
        .filter_map(|(k, v)| match k {
            Value::String(s) => Some((s.clone(), v.clone())),
            _ => None,
        })
        .collect();

    pairs.sort_by_key(|(k, _)| k.len());
    if reverse {
        pairs.reverse();
    }

    pairs.into_iter().collect()
}

pub fn dict_element_append(data: &mut Mapping, key: &str, value: Value, unique: bool) {
    let keyv = Value::String(key.to_string());

    if let Value::Sequence(items) = &value {
        for item in items {
            dict_element_append(data, key, item.clone(), unique);
        }
        return;
    }

    match data.get_mut(&keyv) {
        None => {
            data.insert(keyv, Value::Sequence(vec![value]));
        }
        Some(Value::String(existing)) => {
            let seq = vec![Value::String(existing.clone()), value];
            data.insert(keyv, Value::Sequence(seq));
        }
        Some(Value::Sequence(existing)) => {
            if !unique || !existing.contains(&value) {
                existing.push(value);
            }
        }
        Some(_) => {
            panic!("Unrecognized type for dict_element_append")
        }
    }
}
