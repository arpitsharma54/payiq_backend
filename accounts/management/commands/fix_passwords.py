"""
Management command to fix unhashed passwords in the database.

This command identifies users with plain text passwords and hashes them.
Run this if you created users before implementing proper password hashing in admin.
"""
from django.core.management.base import BaseCommand
from accounts.models import CustomUser
import re


class Command(BaseCommand):
    help = 'Fix unhashed passwords for existing users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without actually changing anything',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Django password hashes start with algorithm identifiers like:
        # pbkdf2_sha256$, argon2$, bcrypt$, etc.
        # Plain text passwords won't have these patterns
        hash_pattern = re.compile(r'^(pbkdf2_|argon2|bcrypt|scrypt|md5\$|sha1\$|crypt\$|bcrypt_sha256\$|pbkdf2_sha1\$)')
        
        users_fixed = 0
        users_skipped = 0
        
        for user in CustomUser.objects.all():
            password = user.password
            
            # Check if password is already hashed
            if hash_pattern.match(password):
                users_skipped += 1
                continue
            
            # Password is not hashed - need to hash it
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f'Would fix password for user: {user.username} (currently plain text)'
                    )
                )
            else:
                # Hash the password
                user.set_password(password)
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Fixed password for user: {user.username}'
                    )
                )
                users_fixed += 1
        
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nDry run complete. Would fix {users_fixed} user(s), skipped {users_skipped} user(s) with already hashed passwords.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nFixed {users_fixed} user(s), skipped {users_skipped} user(s) with already hashed passwords.'
                )
            )

