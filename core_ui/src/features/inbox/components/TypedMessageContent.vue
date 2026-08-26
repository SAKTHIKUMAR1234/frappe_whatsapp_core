<script setup>
	import { computed } from 'vue'
	import {
		ContactRound,
		ExternalLink,
		ListChecks,
		MapPin,
		Package,
		ShieldAlert,
	} from 'lucide-vue-next'
	import { normalizeMessageContent } from '@/features/inbox/utils/messageContent'

	const props = defineProps({ message: { type: Object, required: true } })
	const content = computed(() => normalizeMessageContent(props.message))
	const icon = computed(
		() =>
			({
				contacts: ContactRound,
				location: MapPin,
				order: Package,
				poll: ListChecks,
				system: ShieldAlert,
				unsupported: ShieldAlert,
			})[content.value.kind],
	)
</script>

<template>
	<p v-if="content.kind === 'text'" class="plain-message">{{ content.title }}</p>
	<section v-else class="typed-card" :data-kind="content.kind">
		<header>
			<component :is="icon" v-if="icon" :size="16" aria-hidden="true" />
			<small>{{ content.label }}</small>
		</header>
		<strong>{{ content.title }}</strong>
		<p v-if="content.body">{{ content.body }}</p>
		<small v-if="content.meta" class="typed-meta">{{ content.meta }}</small>

		<ul v-if="content.contacts?.length" class="contact-list">
			<li v-for="(contact, index) in content.contacts" :key="`${contact.name}:${index}`">
				<strong>{{ contact.name }}</strong>
				<span v-if="contact.organization">{{ contact.organization }}</span>
				<a v-for="phone in contact.phones" :key="phone" :href="`tel:${phone}`">{{
					phone
				}}</a>
				<a v-for="email in contact.emails" :key="email" :href="`mailto:${email}`">{{
					email
				}}</a>
			</li>
		</ul>

		<ul v-if="content.items?.length" class="order-list">
			<li v-for="(item, index) in content.items" :key="`${item.id}:${index}`">
				<span>{{ item.id || `Item ${index + 1}` }}</span>
				<strong
					>{{ item.quantity }} ×
					{{ [item.currency, item.price].filter(Boolean).join(' ') }}</strong
				>
			</li>
		</ul>

		<ul v-if="content.options?.length" class="poll-options">
			<li v-for="option in content.options" :key="option">{{ option }}</li>
		</ul>

		<a v-if="content.url" :href="content.url" target="_blank" rel="noreferrer">
			{{ content.kind === 'location' ? 'Open map' : 'Open source' }}
			<ExternalLink :size="13" aria-hidden="true" />
		</a>
	</section>
</template>

<style scoped>
	.plain-message,
	.typed-card p {
		margin: 0;
		white-space: pre-wrap;
	}
	.typed-card {
		min-width: min(260px, 66vw);
		display: grid;
		gap: 7px;
	}
	.typed-card header,
	.typed-card > a,
	.order-list li {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.typed-card header,
	.typed-meta {
		color: var(--wa-muted);
		text-transform: capitalize;
	}
	.typed-card > a,
	.contact-list a {
		width: fit-content;
		color: var(--wa-primary);
		text-decoration: none;
	}
	.typed-card > a:hover,
	.contact-list a:hover {
		text-decoration: underline;
	}
	.contact-list,
	.order-list,
	.poll-options {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.contact-list {
		display: grid;
		gap: 8px;
	}
	.contact-list li {
		display: grid;
		gap: 2px;
		padding-top: 7px;
		border-top: 1px solid var(--wa-border-soft);
	}
	.contact-list span,
	.contact-list a,
	.order-list,
	.poll-options {
		font-size: 12px;
	}
	.order-list li {
		justify-content: space-between;
		padding-block: 4px;
	}
	.poll-options {
		display: grid;
		gap: 5px;
	}
	.poll-options li {
		padding: 6px 8px;
		border: 1px solid var(--wa-border-soft);
		border-radius: 7px;
	}
</style>
