use serde::Serialize;
use serde_yaml::{Mapping, Value};
use std::fs;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum GpruError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("YAML parse error: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("JSON serialize error: {0}")]
    Json(#[from] serde_json::Error),
}

pub fn dict_from_yml(path: impl AsRef<Path>) -> Result<Mapping, GpruError> {
    let path = path.as_ref();
    let text = fs::read_to_string(path)?;
    let root = path.parent().unwrap_or(Path::new("."));
    let mut value: Value = serde_yaml::from_str(&text)?;
    resolve_includes(&mut value, root)?;

    match value {
        Value::Mapping(m) => Ok(m),
        _ => Ok(Mapping::new()),
    }
}

fn resolve_includes(value: &mut Value, root: &Path) -> Result<(), GpruError> {
    match value {
        Value::Tagged(tagged) if tagged.tag == "!include" => {
            let include_target = match &tagged.value {
                Value::String(s) => s.clone(),
                other => serde_yaml::to_string(other)?.trim().to_string(),
            };

            let include_path = if Path::new(&include_target).is_absolute() {
                PathBuf::from(include_target)
            } else {
                root.join(include_target)
            };

            let loaded = dict_from_yml(&include_path)?;
            *value = Value::Mapping(loaded);
            Ok(())
        }
        Value::Mapping(m) => {
            for (_, v) in m.iter_mut() {
                resolve_includes(v, root)?;
            }
            Ok(())
        }
        Value::Sequence(seq) => {
            for v in seq.iter_mut() {
                resolve_includes(v, root)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

pub fn dict_to_yml(path: impl AsRef<Path>, data: &Mapping) -> Result<(), GpruError> {
    let out = serde_yaml::to_string(data)?;
    fs::write(path, out)?;
    Ok(())
}

pub fn dict_to_json<T: Serialize>(path: impl AsRef<Path>, data: &T) -> Result<(), GpruError> {
    let out = serde_json::to_string_pretty(data)?;
    fs::write(path, out)?;
    Ok(())
}
