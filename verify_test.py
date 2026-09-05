from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile

from splitwise_lite import (
    open_store,
    apply_group_definition,
    GroupDefinition,
    Currency,
    sign_up,
    link_user_to_member,
    acting_member,
    MemberNotLinked,
    resolve_sole_group,
    NoGroupConfigured,
    AmbiguousGroup,
    ScryptParams,
)

# Test 1: Idempotency
print("Test 1: Idempotency")
with tempfile.TemporaryDirectory() as tmpdir:
    db_path = Path(tmpdir) / 'test.db'
    
    with open_store(str(db_path)) as store:
        definition = GroupDefinition(
            name='Flat 3',
            currency=Currency('AUD'),
            members=('Sam', 'Ali', 'Jo', 'Kit')
        )
        now = datetime.now(timezone.utc)
        
        # First apply
        result1 = apply_group_definition(store, definition, now=now)
        print(f'  First: created={result1.group_created}, added={len(result1.members_added)}')
        assert result1.group_created == True
        group1 = result1.group
    
    # Re-open store
    with open_store(str(db_path)) as store:
        # Second apply with same definition
        result2 = apply_group_definition(store, definition, now=now)
        print(f'  Second: created={result2.group_created}, added={len(result2.members_added)}')
        assert result2.group_created == False
        assert len(result2.members_added) == 0
        assert result2.group.id == group1.id

print('  PASS')

# Test 2: Add one member with earlier clock
print("Test 2: Add member with earlier clock")
with tempfile.TemporaryDirectory() as tmpdir:
    db_path = Path(tmpdir) / 'test.db'
    
    with open_store(str(db_path)) as store:
        def1 = GroupDefinition(
            name='Flat 3',
            currency=Currency('AUD'),
            members=('Sam', 'Ali', 'Jo')
        )
        now1 = datetime.now(timezone.utc)
        result1 = apply_group_definition(store, def1, now=now1)
        group_id = result1.group.id
    
    # Apply with earlier clock
    with open_store(str(db_path)) as store:
        def2 = GroupDefinition(
            name='Flat 3',
            currency=Currency('AUD'),
            members=('Sam', 'Ali', 'Jo', 'Kit')
        )
        now2 = now1 - timedelta(seconds=60)  # Earlier by 60 seconds
        result2 = apply_group_definition(store, def2, now=now2)
        
        # The new member should still sort last by (created_at, id)
        all_members = store.list_members(group_id)
        names = [m.display_name for m in all_members]
        print(f'  Member order: {names}')
        assert names == ['Sam', 'Ali', 'Jo', 'Kit'], f'Got order: {names}'

print('  PASS')

# Test 3: Link and acting_member workflow
print("Test 3: Link and acting_member")
with tempfile.TemporaryDirectory() as tmpdir:
    db_path = Path(tmpdir) / 'test.db'
    
    with open_store(str(db_path)) as store:
        # Create group
        def1 = GroupDefinition(
            name='Flat 3',
            currency=Currency('AUD'),
            members=('Sam', 'Ali')
        )
        now = datetime.now(timezone.utc)
        result = apply_group_definition(store, def1, now=now)
        group_id = result.group.id
        sam = result.members_added[0]
        ali = result.members_added[1]
        
        # All members should have user_id = None
        for member in store.list_members(group_id):
            assert member.user_id is None
        print(f'  Initial members: {[m.display_name for m in store.list_members(group_id)]}')
    
    # Sign up a user with cheap scrypt params
    with open_store(str(db_path)) as store:
        cheap_params = ScryptParams(n=2, r=1, p=1)
        user = sign_up(
            store,
            email='sam@example.com',
            display_name='Sam User',
            password='password12345',
            now=datetime.now(timezone.utc),
            params=cheap_params
        )
        user_id = user.id
        print(f'  Signed up user: {user.display_name}')
    
    # Before linking, acting_member should raise MemberNotLinked
    with open_store(str(db_path)) as store:
        try:
            acting_member(store, group_id=group_id, user_id=user_id)
            assert False, 'Should have raised MemberNotLinked'
        except MemberNotLinked:
            print(f'  Before link: acting_member raises MemberNotLinked [OK]')
    
    # Link the user to Sam member
    with open_store(str(db_path)) as store:
        linked = link_user_to_member(store, group_id=group_id, member_id=sam.id, user_id=user_id)
        print(f'  Linked user to member: {linked.display_name}')
    
    # Now acting_member should work
    with open_store(str(db_path)) as store:
        member = acting_member(store, group_id=group_id, user_id=user_id)
        assert member.display_name == 'Sam'
        print(f'  After link: acting_member returns {member.display_name} [OK]')

print('  PASS')

print('')
print('All manual verification tests PASSED')
