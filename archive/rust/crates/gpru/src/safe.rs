use serde_yaml::Value;

pub fn safe_float(input: Option<&Value>, default: f64) -> f64 {
    let Some(value) = input else {
        return default;
    };
    match value {
        Value::Number(n) => n.as_f64().unwrap_or(default),
        Value::Bool(b) => {
            if *b {
                1.0
            } else {
                0.0
            }
        }
        Value::String(s) => {
            let cleaned = s
                .strip_suffix("°c")
                .or_else(|| s.strip_suffix('%'))
                .unwrap_or(s);
            cleaned.parse::<f64>().unwrap_or(default)
        }
        _ => default,
    }
}

pub fn safe_int(input: Option<&Value>, default: i64) -> i64 {
    let value = safe_float(input, default as f64);
    if value == 0.0 {
        default
    } else {
        value as i64
    }
}

pub fn safe_list(input: Option<&Value>) -> Vec<Value> {
    match input {
        Some(Value::String(s)) => vec![Value::String(s.clone())],
        Some(Value::Sequence(items)) => items.iter().filter(|v| !is_falsy(v)).cloned().collect(),
        Some(Value::Mapping(map)) => map.keys().cloned().collect(),
        _ => Vec::new(),
    }
}

fn is_falsy(v: &Value) -> bool {
    matches!(v, Value::Null)
        || matches!(v, Value::Bool(false))
        || matches!(v, Value::Number(n) if n.as_i64() == Some(0) || n.as_u64() == Some(0) || n.as_f64() == Some(0.0))
        || matches!(v, Value::String(s) if s.is_empty())
}
