<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="budget-row">
        <label for="budget-slider" class="budget-label">{{ t('restocking.budgetLabel') }}</label>
        <span class="budget-value">{{ formatMoney(budget) }}</span>
      </div>
      <input
        id="budget-slider"
        v-model.number="budget"
        type="range"
        :min="MIN_BUDGET"
        :max="MAX_BUDGET"
        :step="STEP"
        class="budget-slider"
      />
      <div class="budget-scale">
        <span>{{ formatMoney(MIN_BUDGET) }}</span>
        <span>{{ formatMoney(MAX_BUDGET) }}</span>
      </div>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatMoney(recommendation.budget) }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.recommendedTotal') }}</div>
          <div class="stat-value">{{ formatMoney(recommendation.total_cost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(recommendation.remaining_budget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemCount') }}</div>
          <div class="stat-value">{{ items.length }}</div>
        </div>
      </div>

      <div v-if="orderResult" class="notice success-notice">
        <span>
          {{ t('restocking.orderPlaced', {
            orderNumber: orderResult.order_number,
            date: formatDate(orderResult.expected_delivery_date)
          }) }}
        </span>
        <router-link to="/orders" class="notice-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="orderError" class="notice error-notice">{{ orderError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">
            {{ t('restocking.recommendations') }} ({{ items.length }})
            <span v-if="refreshing" class="updating">{{ t('restocking.updating') }}</span>
          </h3>
          <button
            type="button"
            class="btn-primary"
            :disabled="items.length === 0 || placing || refreshing"
            @click="placeOrder"
          >
            {{ placing ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="items.length === 0" class="empty-state">{{ t('restocking.empty') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.demandGap') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.item_sku">
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ item.item_name }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ trendLabel(item.trend) }}</span>
                </td>
                <td class="num">{{ item.demand_gap.toLocaleString() }}</td>
                <td class="num"><strong>{{ item.quantity.toLocaleString() }}</strong></td>
                <td class="num">{{ formatMoney(item.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ formatMoney(item.line_total, 2) }}</strong></td>
                <td class="num">{{ item.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale } = useI18n()

    const MIN_BUDGET = 0
    const MAX_BUDGET = 10000
    const STEP = 100
    const DEBOUNCE_MS = 250

    const budget = ref(5000)
    const recommendation = ref({ budget: 5000, total_cost: 0, remaining_budget: 5000, items: [] })
    const loading = ref(true)
    const refreshing = ref(false)
    const error = ref(null)
    const placing = ref(false)
    const orderResult = ref(null)
    const orderError = ref(null)

    const items = computed(() => recommendation.value.items || [])

    let timer = null
    let requestId = 0

    const loadRecommendations = async () => {
      const myId = ++requestId
      const requestedBudget = budget.value
      try {
        refreshing.value = true
        const data = await api.getRestockRecommendations(requestedBudget)
        if (myId !== requestId) return // stale response
        recommendation.value = data
        error.value = null
      } catch (err) {
        if (myId !== requestId) return
        error.value = t('restocking.loadError') + ': ' + (err.response?.data?.detail || err.message)
      } finally {
        if (myId === requestId) {
          loading.value = false
          refreshing.value = false
        }
      }
    }

    watch(budget, () => {
      clearTimeout(timer)
      timer = setTimeout(loadRecommendations, DEBOUNCE_MS)
    })

    const placeOrder = async () => {
      if (items.value.length === 0 || placing.value) return
      placing.value = true
      orderError.value = null
      orderResult.value = null
      try {
        orderResult.value = await api.createRestockOrder({
          budget: recommendation.value.budget,
          items: items.value.map(i => ({ item_sku: i.item_sku, quantity: i.quantity }))
        })
      } catch (err) {
        orderError.value = err.response?.data?.detail || t('restocking.orderError') + ': ' + err.message
      } finally {
        placing.value = false
      }
    }

    const formatMoney = (value, decimals = 0) => {
      const n = Number(value)
      if (!Number.isFinite(n)) return '-'
      return n.toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
      })
    }

    const formatDate = (dateString) => {
      const d = new Date(dateString)
      if (isNaN(d.getTime())) return '-'
      return d.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    const trendLabel = (trend) => {
      const key = `trends.${trend}`
      const label = t(key)
      return label === key ? trend : label
    }

    onMounted(loadRecommendations)
    onBeforeUnmount(() => clearTimeout(timer))

    return {
      t,
      MIN_BUDGET,
      MAX_BUDGET,
      STEP,
      budget,
      recommendation,
      items,
      loading,
      refreshing,
      error,
      placing,
      orderResult,
      orderError,
      placeOrder,
      formatMoney,
      formatDate,
      trendLabel
    }
  }
}
</script>

<style scoped>
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  accent-color: #3b82f6;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 0.25rem;
}

.updating {
  margin-left: 0.75rem;
  font-size: 0.813rem;
  font-weight: 500;
  color: #64748b;
}

.num {
  text-align: right;
}

.btn-primary {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.notice {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 0.875rem 1.25rem;
  border-radius: 10px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
  font-weight: 500;
}

.success-notice {
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
}

.error-notice {
  background: #fee2e2;
  border: 1px solid #fca5a5;
  color: #991b1b;
}

.notice-link {
  color: #065f46;
  font-weight: 700;
  text-decoration: underline;
  white-space: nowrap;
}
</style>
