-- Supabase Database Schema for OpenRouter AI Chatbot

-- Pre-clean existing manual tables to avoid naming conflicts
drop table if exists public.favorites cascade;
drop table if exists public.chat_files cascade;
drop table if exists public.messages cascade;
drop table if exists public.conversations cascade;
drop table if exists public.user_preferences cascade;
drop table if exists public.profiles cascade;
drop table if exists public.api_usage cascade;

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- PROFILES TABLE
create table public.profiles (
    id uuid references auth.users on delete cascade primary key,
    email text,
    username text,
    avatar_url text,
    updated_at timestamp with time zone default now()
);

-- USER PREFERENCES TABLE
create table public.user_preferences (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users on delete cascade not null unique,
    theme text default 'dark' not null,
    default_model text default 'google/gemini-2.5-flash' not null,
    system_prompt text default 'You are a helpful, smart, and friendly AI assistant.' not null,
    created_at timestamp with time zone default now() not null,
    updated_at timestamp with time zone default now() not null
);

-- CONVERSATIONS TABLE
create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users on delete cascade not null,
    title text not null,
    model text not null,
    is_archived boolean default false not null,
    is_pinned boolean default false not null,
    created_at timestamp with time zone default now() not null,
    updated_at timestamp with time zone default now() not null
);

-- MESSAGES TABLE
create table public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid references public.conversations on delete cascade not null,
    user_id uuid references auth.users on delete cascade not null,
    role text not null check (role in ('user', 'assistant', 'system')),
    content text not null,
    reasoning text, -- Thinking/reasoning process from reasoning models
    token_usage jsonb default '{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}'::jsonb,
    response_time double precision, -- in seconds
    created_at timestamp with time zone default now() not null
);

-- FAVORITES TABLE
create table public.favorites (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users on delete cascade not null,
    message_id uuid references public.messages on delete cascade not null,
    created_at timestamp with time zone default now() not null,
    unique(user_id, message_id)
);

-- CHAT FILES TABLE (Future Uploads)
create table public.chat_files (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid references public.conversations on delete cascade not null,
    message_id uuid references public.messages on delete cascade,
    user_id uuid references auth.users on delete cascade not null,
    file_name text not null,
    file_type text not null,
    file_url text not null,
    file_size integer not null, -- in bytes
    created_at timestamp with time zone default now() not null
);

-- API USAGE TABLE (Analytics)
create table public.api_usage (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users on delete cascade not null,
    model text not null,
    tokens_prompt integer default 0 not null,
    tokens_completion integer default 0 not null,
    estimated_cost double precision default 0.0 not null,
    created_at timestamp with time zone default now() not null
);

-- INDEXES FOR PERFORMANCE
create index idx_conversations_user_id on public.conversations(user_id);
create index idx_messages_conversation_id on public.messages(conversation_id);
create index idx_favorites_user_id on public.favorites(user_id);
create index idx_chat_files_conversation_id on public.chat_files(conversation_id);
create index idx_api_usage_user_id on public.api_usage(user_id);

-- ENABLE ROW LEVEL SECURITY (RLS)
alter table public.profiles enable row level security;
alter table public.user_preferences enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.favorites enable row level security;
alter table public.chat_files enable row level security;
alter table public.api_usage enable row level security;

-- RLS POLICIES

-- Profiles
create policy "Users can view their own profile."
    on public.profiles for select
    using (auth.uid() = id);

create policy "Users can update their own profile."
    on public.profiles for update
    using (auth.uid() = id);

-- User Preferences
create policy "Users can view their own preferences."
    on public.user_preferences for select
    using (auth.uid() = user_id);

create policy "Users can update their own preferences."
    on public.user_preferences for update
    using (auth.uid() = user_id);

create policy "Users can insert their own preferences."
    on public.user_preferences for insert
    with check (auth.uid() = user_id);

-- Conversations
create policy "Users can view their own conversations."
    on public.conversations for select
    using (auth.uid() = user_id);

create policy "Users can create their own conversations."
    on public.conversations for insert
    with check (auth.uid() = user_id);

create policy "Users can update their own conversations."
    on public.conversations for update
    using (auth.uid() = user_id);

create policy "Users can delete their own conversations."
    on public.conversations for delete
    using (auth.uid() = user_id);

-- Messages
create policy "Users can view messages in their conversations."
    on public.messages for select
    using (
        exists (
            select 1 from public.conversations
            where conversations.id = messages.conversation_id
            and conversations.user_id = auth.uid()
        )
    );

create policy "Users can insert messages into their conversations."
    on public.messages for insert
    with check (
        exists (
            select 1 from public.conversations
            where conversations.id = messages.conversation_id
            and conversations.user_id = auth.uid()
        )
    );

-- Favorites
create policy "Users can manage their own favorites."
    on public.favorites for all
    using (auth.uid() = user_id);

-- Chat Files
create policy "Users can manage files in their conversations."
    on public.chat_files for all
    using (auth.uid() = user_id);

-- API Usage
create policy "Users can view their own api usage logs."
    on public.api_usage for select
    using (auth.uid() = user_id);

create policy "Users can insert their own api usage logs."
    on public.api_usage for insert
    with check (auth.uid() = user_id);

-- PROFILE TRIGGER ON SIGNUP
-- Automatically creates profile and preferences when a user signs up.
create or replace function public.handle_new_user()
returns trigger as $$
begin
    -- Create profile
    insert into public.profiles (id, email, username, avatar_url)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data->>'username', split_part(new.email, '@', 1)),
        new.raw_user_meta_data->>'avatar_url'
    );

    -- Create user preferences
    insert into public.user_preferences (user_id)
    values (new.id);

    return new;
end;
$$ language plpgsql security definer;

-- Trigger execution
create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();
