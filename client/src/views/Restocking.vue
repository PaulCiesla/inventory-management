<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div v-if="placedOrder" class="banner success">
        {{ t('restocking.orderPlaced', { orderNumber: placedOrder.order_number }) }}
        <router-link to="/orders">{{ t('restocking.viewInOrders') }}</router-link>
      </div>

      <div v-if="candidates.length === 0" class="card">
        <p class="empty-state">{{ t('restocking.noRecommendations') }}</p>
      </div>

      <template v-else>
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">{{ t('restocking.budgetLabel') }}</h3>
            <span class="budget-value">{{ formatCurrency(budget, currentCurrency) }}</span>
          </div>
          <input
            v-model.number="budget"
            type="range"
            min="0"
            :max="maxBudget"
            :step="budgetStep"
            class="budget-slider"
          />

          <div v-if="submitError" class="banner error">{{ submitError }}</div>

          <div v-if="minLineCost !== null && includedCount === 0" class="banner warning">
            {{ t('restocking.budgetTooLow', { amount: formatCurrency(minLineCost, currentCurrency) }) }}
          </div>
        </div>

        <div class="stats-grid">
          <div class="stat-card info">
            <div class="stat-label">{{ t('restocking.itemsSelected', { count: includedCount }) }}</div>
            <div class="stat-value">{{ formatCurrency(estimatedTotal, currentCurrency) }}</div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
            <button
              class="btn-primary"
              :disabled="includedCount === 0 || submitting"
              @click="placeOrder"
            >
              {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
            </button>
          </div>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th>{{ t('inventory.table.itemName') }}</th>
                  <th>{{ t('restocking.trend') }}</th>
                  <th>{{ t('restocking.quantity') }}</th>
                  <th>{{ t('restocking.unitCost') }}</th>
                  <th>{{ t('restocking.lineTotal') }}</th>
                  <th>{{ t('restocking.leadTime') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in recommendations"
                  :key="row.sku"
                  :class="{ excluded: !row.included }"
                >
                  <td>{{ translateProductName(row.name) }}</td>
                  <td>
                    <span :class="['badge', trendBadgeClass(row.trend)]">
                      {{ t(`trends.${row.trend}`) }}
                    </span>
                  </td>
                  <td>{{ row.quantity }}</td>
                  <td>
                    {{ formatCurrency(row.unit_cost, currentCurrency) }}
                    <span v-if="row.cost_source === 'synthesized'" class="muted-note">
                      ({{ t('restocking.synthesizedNote') }})
                    </span>
                  </td>
                  <td>{{ formatCurrency(row.line_cost, currentCurrency) }}</td>
                  <td>{{ row.lead_time_days }} {{ t('restocking.days') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const demand = ref([])

    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const placedOrder = ref(null)

    // Restock candidates are demand-forecast items where demand is expected to exceed
    // current levels (gap > 0). Decreasing/flat items never need restocking.
    const candidates = computed(() => {
      return demand.value
        .map(item => ({ ...item, gap: item.forecasted_demand - item.current_demand }))
        .filter(item => item.gap > 0)
    })

    // All budget/cost math stays in USD (the API's base currency). formatCurrency() is
    // only used at render time to convert to the display currency (e.g. JPY).
    const maxBudget = computed(() => {
      return Math.ceil(candidates.value.reduce((sum, item) => sum + item.gap * item.unit_cost, 0))
    })

    const budgetStep = computed(() => Math.max(1, Math.round(maxBudget.value / 100)))

    // Rank candidates: increasing trend first, then by gap size (largest shortfall first).
    const rankedCandidates = computed(() => {
      return candidates.value.slice().sort((a, b) => {
        if (a.trend === 'increasing' && b.trend !== 'increasing') return -1
        if (b.trend === 'increasing' && a.trend !== 'increasing') return 1
        return b.gap - a.gap
      })
    })

    // Greedy fill: walk the ranked list and include any item whose line cost still fits
    // within the remaining budget. We keep iterating past items that don't fit so
    // smaller/cheaper items further down the list still get a chance.
    const recommendations = computed(() => {
      let runningTotal = 0
      return rankedCandidates.value.map(item => {
        const lineCost = item.gap * item.unit_cost
        let included = false
        if (runningTotal + lineCost <= budget.value) {
          included = true
          runningTotal += lineCost
        }
        return {
          id: item.id,
          sku: item.item_sku,
          name: item.item_name,
          trend: item.trend,
          quantity: item.gap,
          unit_cost: item.unit_cost,
          line_cost: lineCost,
          lead_time_days: item.lead_time_days,
          cost_source: item.cost_source,
          included
        }
      })
    })

    const includedRows = computed(() => recommendations.value.filter(row => row.included))
    const includedCount = computed(() => includedRows.value.length)
    const estimatedTotal = computed(() => includedRows.value.reduce((sum, row) => sum + row.line_cost, 0))

    const minLineCost = computed(() => {
      if (recommendations.value.length === 0) return null
      return Math.min(...recommendations.value.map(row => row.line_cost))
    })

    const trendBadgeClass = (trend) => {
      const map = { increasing: 'success', stable: 'info', decreasing: 'warning' }
      return map[trend] || 'info'
    }

    const loadDemand = async () => {
      try {
        loading.value = true
        error.value = null
        demand.value = await api.getEnrichedDemand()
        // Seed the budget at half of the theoretical max once data is available
        budget.value = Math.round(maxBudget.value / 2)
      } catch (err) {
        error.value = 'Failed to load demand forecast: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (includedCount.value === 0 || submitting.value) return

      submitting.value = true
      submitError.value = null
      try {
        const items = includedRows.value.map(row => ({
          sku: row.sku,
          name: row.name,
          quantity: row.quantity,
          unit_price: row.unit_cost,
          lead_time_days: row.lead_time_days
        }))
        placedOrder.value = await api.createRestockingOrder({ items, budget: budget.value })
      } catch (err) {
        submitError.value = 'Failed to place restocking order: ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadDemand)

    return {
      t,
      currentCurrency,
      translateProductName,
      formatCurrency,
      loading,
      error,
      candidates,
      budget,
      maxBudget,
      budgetStep,
      recommendations,
      includedCount,
      estimatedTotal,
      minLineCost,
      trendBadgeClass,
      submitting,
      submitError,
      placedOrder,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-value {
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  margin: 0.5rem 0 0;
  accent-color: #3b82f6;
}

.empty-state {
  padding: 1.5rem 0;
  text-align: center;
  color: #64748b;
}

.muted-note {
  color: #94a3b8;
  font-size: 0.75rem;
}

.banner {
  padding: 0.875rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
  margin-top: 1rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.banner.success {
  background: #d1fae5;
  color: #065f46;
}

.banner.success a {
  color: #065f46;
  font-weight: 600;
  text-decoration: underline;
}

.banner.warning {
  background: #fed7aa;
  color: #92400e;
}

.banner.error {
  background: #fecaca;
  color: #991b1b;
}

tr.excluded {
  opacity: 0.45;
}

.btn-primary {
  padding: 0.5rem 1.25rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn-primary:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
</style>
