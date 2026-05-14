#[derive(Clone, Debug, Eq)]
pub struct Y2List {
    pub data: Vec<String>,
    token: String,
}

impl Y2List {
    pub fn new(input: Option<&str>) -> Self {
        let data = input
            .map(|s| {
                s.split(|c: char| !c.is_ascii_alphanumeric())
                    .filter(|s| !s.is_empty())
                    .map(|s| s.to_string())
                    .collect()
            })
            .unwrap_or_default();
        Self {
            data,
            token: String::new(),
        }
    }

    pub fn head(&self) -> Option<&str> {
        self.data.first().map(|s| s.as_str())
    }
    pub fn tail(&self) -> Option<&str> {
        self.data.last().map(|s| s.as_str())
    }
}

impl PartialEq for Y2List {
    fn eq(&self, other: &Self) -> bool {
        self.data == other.data
    }
}

impl std::fmt::Display for Y2List {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.data.join(&self.token))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Y2Path {
    pub data: Vec<String>,
}

impl Y2Path {
    pub fn new(parts: &[&str]) -> Self {
        let mut out = Vec::new();
        for p in parts {
            out.extend(
                p.split('/')
                    .filter(|s| !s.is_empty())
                    .map(|s| s.to_string()),
            );
        }
        Self { data: out }
    }

    pub fn head(&self) -> Option<&str> {
        self.data.first().map(|s| s.as_str())
    }
    pub fn tail(&self) -> Option<&str> {
        self.data.last().map(|s| s.as_str())
    }
}

impl std::fmt::Display for Y2Path {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.data.join("/"))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Y2Topic(pub Y2Path);

impl Y2Topic {
    pub fn new(path: &str) -> Self {
        Self(Y2Path::new(&[path]))
    }
    pub fn is_wildcard(&self) -> bool {
        self.0.data.iter().any(|p| p == "#" || p == "+")
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Y2Slug {
    pub data: Vec<String>,
}

impl Y2Slug {
    pub fn new(input: &str) -> Self {
        let trimmed = input.split('@').next().unwrap_or_default();
        let data = trimmed
            .split('_')
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string())
            .collect();
        Self { data }
    }

    pub fn head(&self) -> Option<&str> {
        self.data.first().map(|s| s.as_str())
    }
    pub fn tail(&self) -> Option<&str> {
        self.data.last().map(|s| s.as_str())
    }
}

impl std::fmt::Display for Y2Slug {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.data.join("_"))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Y2Eid {
    pub ns: String,
    pub domain: String,
    pub slug: Y2Slug,
}

impl Y2Eid {
    pub const DEFAULT_NS: &'static str = "yala";
    pub const DEFAULT_DOMAIN: &'static str = "entity";

    pub fn parse(raw: &str) -> Result<Self, &'static str> {
        if raw.is_empty() {
            return Err("y2eid: empty input");
        }

        let mut ns = Self::DEFAULT_NS.to_string();
        let mut domain = String::new();
        let mut rem = raw.to_string();

        if let Some((d, r)) = rem.split_once('.') {
            domain = d.to_string();
            rem = r.to_string();
        }
        if let Some((s, n)) = rem
            .rsplit_once('@')
            .map(|(s, n)| (s.to_string(), n.to_string()))
        {
            rem = s;
            ns = n;
        }

        if domain.is_empty() {
            domain = Self::DEFAULT_DOMAIN.to_string();
        }

        Ok(Self {
            ns,
            domain,
            slug: Y2Slug::new(&rem),
        })
    }

    pub fn entity_id(&self) -> String {
        format!("{}.{}", self.domain, self.slug)
    }
}

impl std::fmt::Display for Y2Eid {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}.{}@{}", self.domain, self.slug, self.ns)
    }
}
