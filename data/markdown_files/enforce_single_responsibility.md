---
rule_id: enforce-single-responsibility
principle: Enforce Single Responsibility
category: architecture, code-quality
tags: [SRP, single-responsibility, separation-of-concerns, cohesion, coupling, testability, protocols, dependency-injection]
severity: high
language: python
---

# Rule: Enforce Single Responsibility — One Reason to Change

## Core Constraint

Every function, class, and service must have **exactly one reason to change**. When a unit owns multiple concerns — validation, persistence, hashing, emailing, logging, orchestration — a change to any one concern risks breaking all the others, and testing any one concern requires constructing all the others. Decompose by responsibility; couple only through narrow, swappable interfaces.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: One class owns every concern
```python
# VIOLATION: validates, hashes, persists, emails, and logs — five reasons to change
class BadUserRegistration:
    def register(self, username: str, email: str, password: str) -> bool:
        # 1. Validate
        if not username or len(username) < 3:
            print("Error: username too short")
            return False
        if "@" not in email:
            print("Error: invalid email")
            return False

        # 2. Hash password
        hashed = hashlib.sha256(password.encode()).hexdigest()

        # 3. Persist (simulated)
        print(f"[DB] INSERT INTO users VALUES ('{username}', '{email}', '{hashed}')")

        # 4. Send welcome email
        print(f"[SMTP] To: {email}, Subject: Welcome {username}!")

        # 5. Log the event
        print(f"[LOG] {datetime.now()} — registered user '{username}'")

        return True

# Consequence: changing the email provider forces touching persistence logic.
# Testing the validator requires constructing a class that also talks to a database.
# Swapping the hash algorithm risks breaking the email template.
```

### ❌ Anti-Pattern 2: Business logic embedded in the orchestrator
```python
# VIOLATION: the service encodes a business rule (duplicate-email policy)
# instead of only coordinating pre-built specialists.
class UserRegistrationService:
    def register_new_user(self, request):
        # This is a business rule, not an orchestration step.
        # The service now has TWO reasons to change:
        # (a) the sequence of registration steps
        # (b) the policy around duplicate accounts
        if self._repository.user_exists_with_email(request.email):
            duplicate_error = [f"An account with email '{request.email}' already exists"]
            self._logger.log_failed_registration_attempt(request, duplicate_error)
            return RegistrationOutcome(succeeded=False, errors=duplicate_error)
        ...
```

### ❌ Anti-Pattern 3: One class spanning two distinct workflows
```python
# VIOLATION: hash_password is registration-time; password_matches_hash is
# login-time. Any future authentication service must now depend on
# PasswordHasher, coupling two unrelated workflows.
class PasswordHasher:
    def hash_password(self, plain_text_password: str) -> str: ...
    def password_matches_hash(self, plain_text_password: str, stored_hash: str) -> bool: ...
```

### ❌ Anti-Pattern 4: Domain model owns an infrastructural concern
```python
# VIOLATION: the domain object decides when it was created,
# coupling the model to wall-clock time and making it non-deterministic.
@dataclass
class NewUser:
    username: str
    email: str
    password_hash: str
    registered_at: datetime = field(default_factory=datetime.now)  # ← belongs in service layer
```

### ❌ Anti-Pattern 5: A unit self-instantiates its own backend dependency
```python
# VIOLATION: RegistrationEventLogger constructs its own logging.Logger internally.
# If the logging backend changes, the class itself must change — it cannot
# receive an injected logger, making it harder to test and narrowly responsible.
class RegistrationEventLogger:
    def __init__(self) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)  # ← inject instead
```

### ❌ Anti-Pattern 6: Test code co-located in the production module
```python
# VIOLATION: importing unittest.mock and defining test_* functions at module
# level gives the module a second reason to change — test strategy evolution.
# Tests must live in a separate file that imports the production module.
from unittest.mock import MagicMock

def test_email_sender_is_replaceable_with_mock() -> None:
    mock_email_sender = MagicMock()
    ...
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Decompose into focused, named specialists
```python
# Each class has exactly one reason to change, stated explicitly.

class RegistrationRequestValidator:
    """Reason to change: business rules around acceptable usernames/emails/passwords."""
    _MINIMUM_USERNAME_LENGTH = 3
    _MINIMUM_PASSWORD_LENGTH = 8
    _EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    def validate(self, request: UserRegistrationRequest) -> ValidationResult:
        errors: list[str] = []
        if len(request.username) < self._MINIMUM_USERNAME_LENGTH:
            errors.append(f"Username must be at least {self._MINIMUM_USERNAME_LENGTH} characters")
        if not self._EMAIL_PATTERN.match(request.email):
            errors.append("Email address is not valid")
        if len(request.password) < self._MINIMUM_PASSWORD_LENGTH:
            errors.append(f"Password must be at least {self._MINIMUM_PASSWORD_LENGTH} characters")
        return ValidationResult.failure(*errors) if errors else ValidationResult.success()


class PasswordHasher:
    """Reason to change: switching hashing algorithms (e.g. sha256 → bcrypt)."""
    def hash_password(self, plain_text_password: str) -> str:
        salt   = os.urandom(16).hex()
        digest = hashlib.sha256(f"{salt}{plain_text_password}".encode()).hexdigest()
        return f"{salt}${digest}"


class PasswordVerifier:
    """Reason to change: login-time credential verification strategy. Separate from hashing."""
    def password_matches_hash(self, plain_text_password: str, stored_hash: str) -> bool:
        salt, digest = stored_hash.split("$", 1)
        candidate   = hashlib.sha256(f"{salt}{plain_text_password}".encode()).hexdigest()
        return candidate == digest


class RegistrationEventLogger:
    """Reason to change: log format, destination, or verbosity."""
    def __init__(self, logger: logging.Logger) -> None:   # ← injected, not self-constructed
        self._logger = logger

    def log_successful_registration(self, user: NewUser) -> None:
        self._logger.info(
            "New user registered | username='%s' email='%s' at=%s",
            user.username, user.email, user.registered_at.isoformat(),
        )

    def log_failed_registration_attempt(
        self, request: UserRegistrationRequest, errors: list[str]
    ) -> None:
        self._logger.warning(
            "Registration rejected | username='%s' email='%s' reasons=%s",
            request.username, request.email, errors,
        )
```

### ✅ Pattern 2: Business rules belong in a dedicated domain guard, not the orchestrator
```python
# Duplicate-email policy lives in its own unit — the service never encodes it.
class UniqueEmailValidator:
    """Reason to change: the policy around whether duplicate accounts are permitted."""
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def validate(self, email: str) -> ValidationResult:
        if self._repository.user_exists_with_email(email):
            return ValidationResult.failure(
                f"An account with email '{email}' already exists"
            )
        return ValidationResult.success()
```

### ✅ Pattern 3: Protocol-based abstractions make each unit swappable
```python
class UserRepository(Protocol):
    """Reason to change: switching persistence technology."""
    def save_user(self, user: NewUser) -> None: ...
    def user_exists_with_email(self, email: str) -> bool: ...

class WelcomeEmailSender(Protocol):
    """Reason to change: changing email provider or welcome message content."""
    def send_welcome_email(self, user: NewUser) -> None: ...

class InMemoryUserRepository:
    """Concrete implementation — substitutable in tests with zero changes elsewhere."""
    def __init__(self) -> None:
        self._store: dict[str, NewUser] = {}

    def save_user(self, user: NewUser) -> None:
        self._store[user.email] = user

    def user_exists_with_email(self, email: str) -> bool:
        return email in self._store
```

### ✅ Pattern 4: Orchestrator coordinates — it does not compute
```python
class UserRegistrationService:
    """
    Reason to change: the sequence or conditions of the registration flow only.
    Owns no business logic; delegates every concern to a specialist.
    """
    def __init__(
        self,
        validator:       RegistrationRequestValidator,
        unique_email:    UniqueEmailValidator,         # ← business rule extracted here
        hasher:          PasswordHasher,
        repository:      UserRepository,
        email_sender:    WelcomeEmailSender,
        logger:          RegistrationEventLogger,
    ) -> None:
        self._validator    = validator
        self._unique_email = unique_email
        self._hasher       = hasher
        self._repository   = repository
        self._email_sender = email_sender
        self._logger       = logger

    def register_new_user(self, request: UserRegistrationRequest) -> RegistrationOutcome:
        for validation in (self._validator.validate(request),
                           self._unique_email.validate(request.email)):
            if not validation.is_valid:
                self._logger.log_failed_registration_attempt(request, validation.errors)
                return RegistrationOutcome(succeeded=False, errors=validation.errors)

        new_user = NewUser(
            username      = request.username,
            email         = request.email,
            password_hash = self._hasher.hash_password(request.password),
            registered_at = datetime.now(),    # ← infrastructural concern: service layer owns it
        )
        self._repository.save_user(new_user)
        self._email_sender.send_welcome_email(new_user)
        self._logger.log_successful_registration(new_user)
        return RegistrationOutcome(succeeded=True, new_user=new_user)
```

### ✅ Pattern 5: Tests in a separate file, each responsibility tested in isolation
```python
# tests/test_registration.py  ← separate file; never co-located with production code

from myapp.registration import (
    RegistrationRequestValidator, UserRegistrationRequest,
    PasswordHasher, InMemoryUserRepository, NewUser,
)
from unittest.mock import MagicMock

def test_validator_rejects_short_username() -> None:
    validator = RegistrationRequestValidator()
    result    = validator.validate(
        UserRegistrationRequest(username="ab", email="x@y.com", password="strongpass")
    )
    assert not result.is_valid
    assert any("Username" in e for e in result.errors)

def test_email_sender_replaceable_with_mock() -> None:
    # Because WelcomeEmailSender is a single-responsibility Protocol,
    # swapping it for a mock requires zero changes to any other class.
    mock_sender = MagicMock()
    service = UserRegistrationService(
        ...,
        email_sender=mock_sender,    # ← drop-in replacement
    )
    service.register_new_user(...)
    mock_sender.send_welcome_email.assert_called_once()
```

---

## Decision Checklist

| Question | Required Answer |
|---|---|
| Can you state the class's single reason to change in one sentence? | ✅ Yes |
| Does the orchestrator contain zero business logic (only sequencing)? | ✅ Yes |
| Are business rules each owned by a dedicated domain guard or validator? | ✅ Yes |
| Are operations from different workflows (e.g. register vs. login) in separate classes? | ✅ Yes |
| Do all dependencies arrive via injection rather than self-construction? | ✅ Yes |
| Are all abstractions defined as Protocols so backends are swappable? | ✅ Yes |
| Do tests live in a separate file and test each responsibility in isolation? | ✅ Yes |
| Does the domain model contain only domain data — no timestamps, no I/O? | ✅ Yes |

---

## Key Principle Summary

> **A class should have one, and only one, reason to change.** When a class owns validation, hashing, persistence, emailing, and logging simultaneously, every one of those concerns becomes a loaded gun pointed at every other. Decompose by responsibility, name each unit after what it does, inject dependencies through narrow Protocol interfaces, and let the orchestrator sequence specialists without becoming one.